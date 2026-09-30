using System;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Windows.Forms;

internal static class Program
{
	internal static string Root;

	[DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
	private static extern bool SetDllDirectory(string path);

	[STAThread]
	private static void Main(string[] args)
	{
		//IL_01df: Unknown result type (might be due to invalid IL or missing references)
		try
		{
			Root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Dashboard Calculator", "app-21.0.0");
			if (args.Length > 0 && args[0] == "--self-test")
			{
				Root = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "../work/desktop/test-runtime");
			}
			Directory.CreateDirectory(Root);
			string[] array = new string[6] { "index.html", "ford.html", "isuzu.html", "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll", "WebView2Loader.dll" };
			foreach (string text in array)
			{
				using Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(text);
				using MemoryStream memoryStream = new MemoryStream();
				stream.CopyTo(memoryStream);
				byte[] array2 = memoryStream.ToArray();
				string path = Path.Combine(Root, text);
				if (!File.Exists(path) || Convert.ToBase64String(File.ReadAllBytes(path)) != Convert.ToBase64String(array2))
				{
					File.WriteAllBytes(path, array2);
				}
			}
			SetDllDirectory(Root);
			AppDomain.CurrentDomain.AssemblyResolve += delegate(object sender, ResolveEventArgs e)
			{
				string text2 = Path.Combine(Root, new AssemblyName(e.Name).Name + ".dll");
				return File.Exists(text2) ? Assembly.LoadFrom(text2) : null;
			};
			Run(args);
		}
		catch (Exception ex)
		{
			if (args.Length > 0)
			{
				File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "../work/desktop/launch-error.txt"), ex.ToString());
			}
			else
			{
				MessageBox.Show(ex.Message, "Dashboard Calculator", (MessageBoxButtons)0, (MessageBoxIcon)16);
			}
		}
	}

	[MethodImpl(MethodImplOptions.NoInlining)]
	private static void Run(string[] args)
	{
		Application.EnableVisualStyles();
		Application.SetCompatibleTextRenderingDefault(false);
		Application.Run((Form)(object)new Studio(args.Length > 0 && args[0] == "--self-test"));
	}
}
