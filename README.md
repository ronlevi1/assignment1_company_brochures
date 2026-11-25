# מטלה 1 — מחולל חוברות חברה

**מצב ההגשה: ממתינה לאישור ידני של ביקורת שמונה הטענות.** ארבע החוברות הערוכות עומדות בדרישות האורך וההפניות. פלט הזרימה המקורי למועמדי Fathom הסתיים ב־187 מילים ונכשל באימות האורך. העותק בן 242 המילים נערך לאחר ההפקה. דרישת האורך לחוברת כפי שהופקה בזרימה מולאה חלקית בלבד.

## התחלה ב־Windows PowerShell

חלצו את כל תוכן ה־ZIP לתיקייה אחת ופתחו בה PowerShell. הגרסה שנבדקה היא Python 3.14.6. ההתקנה הראשונית דורשת חבילות זמינות; אחרי ההתקנה אפשר להריץ את כל הבדיקות והמחברת מקומית.

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m ipykernel install --sys-prefix --name python3 --display-name "Python 3 (HW1)"
```

## שחזור לא מקוון

השאירו את תיקיית `runs` המחולצת במקומה ואת `FETCH_NEW = False` במחברת. בהרצה זו אין צורך ב־`.env`. הפקודה הראשונה מבטלת בחלון הנוכחי את ההפעלה האופציונלית של בחירת קישורים.

```powershell
Remove-Item Env:RUN_LINK_SELECTION -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m IPython --quick --HistoryManager.enabled=False -c "%run assignment1_brochure_pro.ipynb"
.\.venv\Scripts\python.exe -m nbconvert --to notebook --execute --output offline_replay.ipynb assignment1_brochure_pro.ipynb
.\.venv\Scripts\python.exe -m jupyterlab assignment1_brochure_pro.ipynb
```

ב־JupyterLab בחרו בליבת Python של הפרויקט והפעילו **Run All Cells**. בשלבים 1–2 המחברת בודקת את צילומי דפי הבית ומציגה גם את כשל הבחירה הראשון. שלב 3 מציג הקצאות מקורות מתוך האיסוף המוצלח. שלב 4 מציג פלטים ורשומות אימות היסטוריות. שלב 5 מציג את הסקירה, הניסוי, שמונה ההכרעות המוצעות והעותקים הערוכים. עיון בקובצי Markdown וב־CSV אפשרי גם ללא Python.

## תצורה והפעלה חיה מפורשת

`config.py` מרכז את החברות, ארבעת הממדים, כתובת Gemini התואמת ל־OpenAI והגדרת `max_retries=0`. רק לצורך הפקה חדשה, הכניסו מפתח פרטי ל־`.env` בעורך מקומי. `GEMINI_MODEL=gemini-3.5-flash-lite` ו־`SOURCE_CONTEXT_BUDGET=12000` הן ההגדרות של הראיות המצורפות.

```powershell
if (!(Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
notepad .env
```

הפעולות הבאות מתעדות את מסלול העבודה החי. אין צורך בהן להגשה או לשחזור הממצאים.

| שלב | אופן הפעלה מתיקיית הפרויקט |
|---|---|
| 1. דפי בית | במחברת משנים במפורש ל־`FETCH_NEW = True` ומריצים רק את תאי שלב 1. מתקבלת תיקיית איסוף חדשה. |
| 2. בחירת קישורים | לניסיון מפורש עבור חברה אחת על הקלט השמור: `.\.venv\Scripts\python.exe .\retry_phase2.py --execute --company A` (או `B`). הפקודה בודקת קישוריות ואז מפנה קריאה אחת למודל. |
| 3. איסוף ובניית הקשר | `.\.venv\Scripts\python.exe .\collect_sources.py --execute` קוראת את הבחירות המוצלחות הקבועות של A ו־B ואוספת את חמשת העמודים הנוספים. ללא הדגל מתקבלת תכנית האיסוף המקומית בלבד. |
| 4. הפקה | `.\.venv\Scripts\python.exe .\generate_outputs.py --execute` משתמשת בהקשר הקבוע של שלב 3 ומדלגת על תוצרים שכבר נרשמו. ניסיון חדש לתוצר מסוים אפשרי במפורש עם `--output B-candidate --force`. כל ניסיון נשמר בנפרד. |
| 5. ביקורת וניסוי | מריצים את תאי שלב 5 במחברת לעיון מקומי. בודק אנושי משווה את הציטוטים למקורות ומאשר או מתקן את ההכרעות. |
| 6. אימות הגשה | מריצים את פקודות הבדיקות והשחזור הלא מקוון שלעיל. תוצאות הבדיקה של החבילה נשמרו ב־[verification.txt](verification.txt). |

## מפתח לקבצים ולראיות

- [הדוח בעברית](HW1_Report_Final.pdf) ו[המחברת](assignment1_brochure_pro.ipynb). מחברת ההתחלה הרשמית לא הייתה זמינה. המימוש מבוסס על `day5.ipynb` הכיתתית, המצורפת לעיון.
- [scraper.py](scraper.py) הוא קובץ הכיתה עם פונקציית פענוח משותפת שנוספה לחילוץ כותרת, טקסט מלא וקישורים מאותו HTML. נשמרו ממשקי שתי פונקציות הכיתה ומגבלת התצוגה של 2,000 תווים. `prompts.py` בונה הודעות, `utils.py` מנרמל ובודק, ושלושת סקריפטי ההפעלה שומרים ניסיונות ותוצרים.
- [דפי הבית השמורים](runs/phase1-20261124T144231622541Z/) כוללים HTML, טקסט וקישורים לאחר ששתי בקשות Python [נכשלו ב־ProxyError](runs/phase1-20261124T143448052809Z/requests.jsonl). הלכידה החלופית ב־Chrome מתועדת ללא קוד HTTP או משך שלא דווחו.
- [קלט הבחירה והניסיון הראשון](runs/phase2-for-20261124T144231622541Z/), [בחירת A](runs/phase2-for-20261124T144231622541Z-attempt-04/A/result.json), [בחירת B](runs/phase2-for-20261124T144231622541Z-attempt-02/B/result.json). **attempt-03 הוא תוצר בדיקה סינתטי** שנשמר לזיהוי היסטורי והוחרג מכל ספירת ביצוע אמיתי.
- [מקורות והקשרים](runs/phase3-20261124T220906347169Z/): שבע רשומות A1–A3 ו־B1–B4, שלושה קובצי `context_*.json` עם ההקשר המדויק והקצאות התווים, ויומן חמש הבקשות. דפי הבית בשימוש חוזר.
- תחת `runs/phase4-*/` נמצאים הקריטריונים וכל הניסיונות, כולל כישלונות. לכל תוצר `input.json` עם ההודעות המדויקות ונתיב ההקשר, `result.json` עם היומן והאימות ו־`output.md` עם הטקסט המקורי. `response.json` מכיל תשובת שירות שמורה ו־`events.jsonl` מכיל אירועי זרימה. שימוש בטוקנים מופיע רק כאשר דווח.
- [מפת המקורות והעריכות](phase5/quality_review.md) מקשרת לכל ארבע החוברות וההשוואה המקוריות ולעותק הערוך המתאים. [גרסת הבסיס המקורית](runs/phase4-20261124T222639916451Z/A-customer-baseline/output.md), [ארבעת הקריטריונים והערכת הניסוי](phase5/prompt_experiment.md), [ביקורת לאישור](phase5/claim_audit.csv), [עותקים ערוכים](phase5/reviewed/). כשיש פער בין אימות היסטורי לבין הבדיקה העדכנית, שתי התוצאות נשמרות.
