using System.Reflection;

namespace QbtOs.Imager.Ui;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        var temporaryDirectory = Path.Combine(Path.GetTempPath(), "qbtos-imager-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(temporaryDirectory);
        var backendPath = Path.Combine(temporaryDirectory, "imager.ps1");

        try
        {
            using var resource = Assembly.GetExecutingAssembly().GetManifestResourceStream("QbtOs.Imager.Ui.imager.ps1")
                ?? throw new InvalidOperationException("The embedded imager backend is missing.");
            using (var destination = new FileStream(backendPath, FileMode.CreateNew, FileAccess.Write, FileShare.Read))
            {
                resource.CopyTo(destination);
            }
            Application.Run(new MainForm(backendPath));
        }
        catch (Exception exception)
        {
            MessageBox.Show(exception.Message, "qbtOS Imager", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally
        {
            try { Directory.Delete(temporaryDirectory, true); } catch { }
        }
    }
}
