# Dashboard Calculator v21 (مُستخرج من الـ exe)

سورس مُفكَّك (decompiled) من `Dashboard-Calculator-v21.exe` — تطبيق WinForms + WebView2.

- `Program.cs` / `Studio.cs`: كود C# (نافذة WinForms + جسر رسائل مع WebView2)
- `index.html`, `ford.html`, `isuzu.html`: واجهات الحاسبة (HTML/JS) — مع `theme.css` وهو ملف التصميم المشترك (ألوان الشعار: كحلي + أخضر مزرق)
- ملاحظة: الكود من decompiler، فأسماء المتغيرات المحلية والتعليقات الأصلية غير موجودة.
- البناء: على Windows `dotnet build` (يحتاج .NET Framework 4.0+ و WebView2 Runtime).
