# DashForge (سابقاً Dashboard Calculator) — مُستخرج من الـ exe

سورس مُفكَّك (decompiled) من `Dashboard-Calculator-v21.exe` — تطبيق WinForms + WebView2.

- `Program.cs` / `Studio.cs`: كود C# (نافذة WinForms + جسر رسائل مع WebView2)
- `index.html`: الشاشة الرئيسية. `editor.html`: شاشة عرض وتعديل موحّدة للسيارتين (Ford F150 و Isuzu D-MAX) تُحدَّد بـ `?profile=ford|isuzu`
- ملاحظة: الكود من decompiler، فأسماء المتغيرات المحلية والتعليقات الأصلية غير موجودة.
- البناء: على Windows `dotnet build` (يحتاج .NET Framework 4.0+ و WebView2 Runtime).
