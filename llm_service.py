"""Only provider boundary. Quarantine incomplete responses, including clean EOF without stop."""
import os
import re
from time import monotonic, sleep
from prompt_builder import length_feedback

from storage import attempt_key, dump_json, dump_text


TRANSIENT = {500, 502, 503, 504}


def redact(value, api_key=None):
    text = str(value)
    for key in (api_key, os.environ.get("OPENAI_API_KEY")):
        if isinstance(key, str) and key:
            text = text.replace(key, "[REDACTED]")
    text = re.sub(r"(?i)\b(Bearer|Basic)\s+[^\s,;'\"}]+", "[REDACTED]", text)
    text = re.sub(r"""(?ix)["']?(?:(?:proxy-)?authorization|x-goog-api-key|
                  x-api-key|api[_-]?key|access_token|key)["']?\s*[:=]\s*
                  (?:"[^"]*"|'[^']*'|[^\s&;,}]+)""", "[REDACTED]", text)
    return re.sub(r"\b(?:AIza[\w-]{25,}|sk-[\w-]{12,})", "[REDACTED]", text)


def safe_text(value, api_key=None):
    text = " ".join(redact(value, api_key).split())
    return text if len(text) <= 500 else text[:499] + "…"


def error_details(exc, api_key=None):
    """Read only diagnostics from the response. Never serialize the request or all headers."""
    response = getattr(exc, "response", None)
    http_status = getattr(exc, "status_code", getattr(response, "status_code", None))
    body = getattr(exc, "body", None)
    if body is None and response is not None:
        try:
            body = response.json()
        except ValueError:
            body = response.text
        except RuntimeError:  # An unread streaming HTTP response may have headers only.
            pass
    if isinstance(body, list) and len(body) == 1:
        body = body[0]
    if isinstance(body, dict):
        body = body.get("error", body)
    fields = body if isinstance(body, dict) else {}
    message = fields.get("message") or (body if isinstance(body, str) else None)
    if not message:
        message = getattr(response, "reason_phrase", None) or str(exc) or type(exc).__name__
    details = dict(error=type(exc).__name__, http_status=http_status,
                   provider_message=redact(message, api_key))
    for field, name in (("code", "provider_code"), ("status", "provider_status"), ("type", "provider_type")):
        value = fields.get(field)
        if isinstance(value, (str, int)):
            details[name] = safe_text(value, api_key) if isinstance(value, str) else value
    headers = getattr(response, "headers", {})
    metadata = {name: safe_text(headers[name], api_key) for name in
                ("x-request-id", "x-goog-request-id", "x-guploader-uploadid", "retry-after", "content-type")
                if name in headers}
    if metadata:
        details["response_metadata"] = metadata
    return details


def aggregate_stream(events, update):
    text, error, usage = _read_stream(events, update)
    return text, type(error).__name__ if isinstance(error, BaseException) else error, usage


def _read_stream(events, update, metadata=None):
    parts = []
    finish = None
    usage = {}
    error = None
    chunks = 0
    try:
        for event in events:
            chunks += 1
            usage.update(reported_usage(event))
            choices = getattr(event, "choices", None)
            if not choices:
                continue
            choice = next((c for c in choices if getattr(c, "index", 0) == 0), None)
            if choice is None:
                continue
            chunk = getattr(getattr(choice, "delta", None), "content", None)
            if isinstance(chunk, str) and chunk:
                parts.append(chunk)
                update("".join(parts))
            if getattr(choice, "finish_reason", None):
                finish = choice.finish_reason
    except (Exception, KeyboardInterrupt) as exc:
        error = exc
    if metadata is not None:
        metadata.update(chunks=chunks, finish_reason=finish, text_chars=sum(map(len, parts)),
                        iterator_end="exception" if error is not None else "exhausted")
    if (not isinstance(finish, str) or finish.lower() != "stop") and error is None:
        error = f"incomplete stream: {finish or 'missing finish event'}"
    return "".join(parts), error, usage


def reported_usage(response):
    usage = getattr(response, "usage", None)
    return {name: getattr(usage, name) for name in ("prompt_tokens", "completion_tokens", "total_tokens")
            if isinstance(getattr(usage, name, None), int)}


class ModelService:
    def __init__(self, client, settings, run, resume_attempts=None):
        self.client, self.settings, self.run = client, settings, run
        self.last_failure = None
        self.resume_attempts = dict(resume_attempts or {})

    def validated_writing(self, operation, company, audience, system, user, context, validate, update=None):
        """At most one new sample after completed but invalid text; keep both raw replies."""
        attempt = 1
        resume = self.resume_attempts.get(operation, {})
        samples = 1 if resume.get("had_sample") or resume.get("partial_stream") else 2
        reason = resume.get("length_error", resume.get("reason"))
        for sample in range(1, samples + 1):
            feedback = length_feedback(reason)
            content, attempt = self._with_retries(operation, company, audience, system, feedback + user,
                                                  context, update, attempt, writing=True)
            try:
                details = validate(content)
            except ValueError as exc:
                reason = str(exc)
                self.run.log("validation_failed", operation=operation, attempt=attempt, reason=str(exc))
                if sample == samples:
                    raise
                attempt += 1
                self.run.log("retry", operation=operation, attempt=attempt, reason=str(exc), kind="validation",
                             policy="Regenerate with the same evidence and measured length feedback when applicable")
                continue
            if attempt > 1:
                details["accepted_attempt"] = attempt
            return content, details

    def call(self, operation, company, audience, system, user, context, update=None, *, attempt=1, response_format=None):
        content, _ = self._with_retries(operation, company, audience, system, user, context, update, attempt, response_format)
        return content

    def _with_retries(self, operation, company, audience, system, user, context, update, attempt, response_format=None, *, writing=False):
        messages = [dict(role="system", content=system), dict(role="user", content=user)]
        request = dict(model=self.settings.model, messages=messages, stream=update is not None)
        if response_format is not None:
            request["response_format"] = response_format
        resume = self.resume_attempts.pop(operation, None)
        if resume:
            attempt = resume["attempt"]
            self.run.log("retry", operation=operation, kind="stage_resume", attempt=attempt,
                         reason=resume["reason"], retry_limit=self.settings.provider_retries, delay_s=0)
        for repeat in range(self.settings.provider_retries + 1):
            self.last_failure = None
            try:
                return self._attempt(operation, company, audience, request, context, update, attempt, writing), attempt
            except Exception:
                failure = self.last_failure or {}
                if not failure.get("retryable") or repeat == self.settings.provider_retries:
                    raise
                attempt += 1
                delay = min(2 ** repeat, 4)
                self.run.log("retry", kind="provider", operation=operation, attempt=attempt,
                             reason=f"HTTP {failure['http_status']}", delay_s=delay,
                             retry_limit=self.settings.provider_retries)
                sleep(delay)

    def _attempt(self, operation, company, audience, request, context, update, attempt, writing):
        run = self.run
        key = attempt_key(operation, attempt)
        input_path = f"prompts/{key}.json"
        output_path = f"responses/{key}.txt"
        context_path = f"contexts/{key}.json"
        paths = (input_path, output_path, context_path, f"responses/{key}_error.json")
        if any((run.root / path).exists() for path in paths):
            raise FileExistsError(f"Call already recorded: {key}")
        dump_json(run.root / context_path, context)
        dump_json(run.root / input_path, request)
        fields = dict(operation=operation, company=company, audience=audience, model=self.settings.model,
                      attempt=attempt, input_path=input_path, context_path=context_path,
                      parameters={**{k: v for k, v in request.items() if k != "messages"}, "timeout_s": self.settings.timeout})
        if writing:
            fields["writing_version"] = 2
        run.log("llm_started", **fields)
        start = monotonic()
        status, usage, diagnostics = "failed", {}, {}
        failure = None
        received = False
        api_key = getattr(self.client, "api_key", None)
        try:
            response = self.client.chat.completions.create(**request)
            received = True
            error = None
            if update is not None:
                diagnostics["stream_metadata"] = {}
                content, error, usage = _read_stream(response, update, diagnostics["stream_metadata"])
                close = getattr(response, "close", None)
                if close:
                    try:
                        close()
                    except Exception as exc:
                        error = error or exc
            else:
                usage = reported_usage(response)
                choice = response.choices[0]
                content = choice.message.content or ""
                diagnostics["response_metadata"] = {name: safe_text(value, api_key) for name, value in
                    (("id", getattr(response, "id", None)), ("model", getattr(response, "model", None)),
                     ("request_id", getattr(response, "_request_id", None)), ("finish_reason", choice.finish_reason))
                    if value is not None}
                if choice.finish_reason != "stop":
                    error = f"incomplete response: {choice.finish_reason}"
            dump_text(run.root / output_path, content)
            if error:
                status = "partial"
                if update is not None:
                    run.log("stream_interrupted", operation=operation, attempt=attempt, reason=safe_text(error, api_key))
                if isinstance(error, BaseException):
                    raise error
                raise ValueError(error)
            status = "received"
            return content
        except (Exception, KeyboardInterrupt) as exc:
            diagnostics.update(error_details(exc, api_key))
            diagnostics["retryable"] = not received and diagnostics["http_status"] in TRANSIENT
            error_path = f"responses/{key}_error.json"
            diagnostics["error_path"] = error_path
            if not (run.root / output_path).is_file():
                output_path = error_path
            report = dict(run_id=run.id, **fields, duration_s=monotonic()-start, **diagnostics)
            dump_json(run.root / error_path, report)
            failure = report
            raise
        finally:
            duration = failure["duration_s"] if failure else monotonic()-start
            run.log("llm", **fields, duration_s=duration, success=status == "received", status=status,
                    output_path=output_path, **usage, **diagnostics)
            self.last_failure = failure

