# SmplWise Runtime Auto-Off

אינטגרציית Home Assistant שמגבילה זמן פעולה רצוף של רכיבים בחדר.

בוחרים Area ורשימה מפורשת של רכיבים. לכל רכיב נבחר יש ספירה עצמאית
מהרגע שבו הוא עובר מ־`off` למצב פעיל. כאשר אחד מהם נשאר פעיל ברציפות
במשך הזמן שהוגדר, האינטגרציה מכבה את כל הרכיבים הפעילים שנבחרו. אם רכיב
נשאר פעיל, מרווח בדיקה נפרד קובע מתי יתבצע ניסיון נוסף.

## עקרונות בטיחות

- רק רכיבים שנבחרו במפורש נשלטים; ה־Area משמש לסינון בלבד.
- רכיבים חייבים להשתייך בזמן הביצוע לאותו Area ולתמוך ב־`turn_off`.
- כל קריאת שירות נעשית לרכיב יחיד, כך שכשל אחד אינו מונע טיפול באחרים.
- `unknown`, `unavailable`, רכיב מושבת, רכיב שהועבר חדר או זהות שהשתנתה
  מטופלים בצורה סגורה ובטוחה.
- Group שנבחר במפורש עלול לשלוט בכל חבריו.

## אופן הפעולה

1. מצב `off` פירושו שהרכיב כבוי. כל מצב תקין אחר נחשב פעיל.
2. מעבר מ־`off` למצב פעיל פותח מחזור ומחשב מועד כיבוי לפי הזמן שהוגדר.
3. עדכון מאפיינים או מעבר בין שני מצבים פעילים אינו מאפס את הספירה.
4. כיבוי הרכיב לפני המועד מבטל את המחזור שלו.
5. הרכיב הראשון שמגיע לזמן המרבי מפעיל ניסיון כיבוי לכל הרכיבים
   הפעילים שנבחרו.
6. אם רכיב נשאר פעיל לאחר ניסיון הכיבוי, האינטגרציה מתזמנת בדיקה נוספת
   לפי מרווח הבדיקה הנפרד ומנסה לכבות שוב את הרכיבים שעדיין פעילים.
7. שעת ההדלקה המקורית אינה מתאפסת בין הניסיונות. הבדיקה החוזרת נמשכת
   בכל מרווח בדיקה מוגדר עד שהרכיב נכבה.

לדוגמה: אם נבחרו טלוויזיה, תאורה ומזגן והזמן הוא שעה, מספיק שאחד מהם
יהיה פעיל ברציפות שעה כדי שכל שלושת הרכיבים הפעילים יכובו.

אפשר, לדוגמה, להגדיר כיבוי ראשון לאחר 45 דקות ומרווח בדיקה חוזרת של
5 דקות. במקרה כזה רכיב שנשאר פעיל ייבדק שוב כל 5 דקות, בלי לאפס את
45 הדקות שבהן היה פעיל מלכתחילה.

## ישויות לכל Device

- מתג הפעלה או השהיה של הכלל.
- חיישן בינארי שמציג אם רכיב נבחר כלשהו פעיל.
- חיישן מצב: אתחול, מושבת, המתנה, ספירה, ביצוע, הושלם או שגיאה.
- חיישן שמציג איזה רכיב צפוי להגיע ראשון לזמן המרבי.
- חיישן זמן לכיבוי המתוכנן הבא.
- חיישן זמן לכיבוי האחרון שבוצע.
- Event entity לפעילות: תזמון, ביטול, ביצוע, אין פעולה או כשל.

ה־Device כולל קישור ישיר להגדרות האינטגרציה, ולכן אפשר לערוך ממנו את
החדר, הרכיבים ושני הזמנים.

## התקנה דרך HACS

1. פותחים HACS ובוחרים **Custom repositories**.
2. מוסיפים את `https://github.com/jonioliel/ha-runtime-auto-off` מסוג
   **Integration**.
3. מתקינים את **SmplWise Runtime Auto-Off** ומפעילים מחדש את Home Assistant.
4. עוברים אל **Settings → Devices & services → Add integration** ומוסיפים
   את האינטגרציה.

## התקנה ידנית

מעתיקים את התיקייה `custom_components/runtime_auto_off` אל
`config/custom_components/runtime_auto_off` ומפעילים מחדש את Home Assistant.

## English summary

SmplWise Runtime Auto-Off monitors explicitly selected, area-scoped entities.
Each entity has an independent continuous-active timer. When any selected entity
reaches the configured duration, all selected active entities receive a shutdown
command. Any entity that remains active is checked and retried after the
configured retry interval, which is independent from the initial runtime limit.
Retry deadlines survive restarts, and service success is accepted only when Home
Assistant confirms the entity is off. The integration
creates one first-class Home Assistant device per rule and supports full UI editing.
