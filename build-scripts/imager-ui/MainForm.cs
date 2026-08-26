using System.Diagnostics;
using System.Globalization;
using System.Text;
using System.Text.Json;

namespace QbtOs.Imager.Ui;

internal sealed class MainForm : Form
{
    private readonly string backendPath;
    private readonly TextBox imagePath = new() { Dock = DockStyle.Fill, AllowDrop = true };
    private readonly Button browseButton = new() { Text = "Browse...", AutoSize = true };
    private readonly ComboBox diskList = new() { Dock = DockStyle.Fill, DropDownStyle = ComboBoxStyle.DropDownList };
    private readonly Button refreshButton = new() { Text = "Refresh", AutoSize = true };
    private readonly Label diskDetails = new() { Dock = DockStyle.Fill, AutoSize = true, ForeColor = Color.DimGray };
    private readonly CheckBox createData = new() { Text = "Create QBTOS_DATA partition", Checked = true, AutoSize = true };
    private readonly CheckBox maximumData = new() { Text = "Use maximum available whole GiB", Checked = true, AutoSize = true };
    private readonly NumericUpDown dataSize = new() { Minimum = 1, Maximum = 2047, Value = 8, Width = 100, Enabled = false };
    private readonly ComboBox fileSystem = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 180 };
    private readonly ProgressBar progress = new() { Dock = DockStyle.Fill, Minimum = 0, Maximum = 100 };
    private readonly Label status = new() { Text = "Ready", AutoSize = true, ForeColor = Color.DimGray };
    private readonly TextBox log = new() { Dock = DockStyle.Fill, Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, BackColor = Color.White };
    private readonly Button writeButton = new() { Text = "Write qbtOS image", AutoSize = true, Padding = new Padding(12, 5, 12, 5) };
    private Process? activeProcess;
    private bool isBusy;

    public MainForm(string backendPath)
    {
        this.backendPath = backendPath;
        Text = "qbtOS Imager";
        MinimumSize = new Size(760, 680);
        Size = new Size(860, 760);
        StartPosition = FormStartPosition.CenterScreen;
        AutoScaleMode = AutoScaleMode.Dpi;
        AllowDrop = true;

        var defaultImage = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "images", "sdcard.img"));
        imagePath.Text = File.Exists(defaultImage) ? defaultImage : "";
        fileSystem.Items.AddRange(["NTFS (Windows compatible)", "ext4 (Linux native)"]);
        fileSystem.SelectedIndex = 0;

        Controls.Add(BuildLayout());
        browseButton.Click += BrowseForImage;
        refreshButton.Click += async (_, _) => await RefreshDisksAsync();
        diskList.SelectedIndexChanged += (_, _) => UpdateDiskDetails();
        createData.CheckedChanged += (_, _) => UpdateDataControls();
        maximumData.CheckedChanged += (_, _) => UpdateDataControls();
        writeButton.Click += async (_, _) => await StartWriteAsync();
        imagePath.DragEnter += ImageDragEnter;
        imagePath.DragDrop += ImageDragDrop;
        DragEnter += ImageDragEnter;
        DragDrop += ImageDragDrop;
        Shown += async (_, _) => await RefreshDisksAsync();
        FormClosing += PreventCloseDuringWrite;
        UpdateDataControls();
    }

    private Control BuildLayout()
    {
        var root = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(18), ColumnCount = 1, RowCount = 7 };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        var heading = new Label {
            Text = "Write a qbtOS image to an SD card or removable disk",
            Font = new Font(Font.FontFamily, 14, FontStyle.Bold),
            AutoSize = true,
            Margin = new Padding(3, 0, 3, 12)
        };
        root.Controls.Add(heading);
        root.Controls.Add(BuildImageGroup());
        root.Controls.Add(BuildDiskGroup());
        root.Controls.Add(BuildDataGroup());
        root.Controls.Add(new Label {
            Text = "Warning: the selected whole disk and every filesystem on it will be overwritten.",
            ForeColor = Color.Firebrick,
            Font = new Font(Font, FontStyle.Bold),
            AutoSize = true,
            Margin = new Padding(3, 10, 3, 8)
        });
        root.Controls.Add(BuildStatusGroup());

        var actions = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft, AutoSize = true };
        actions.Controls.Add(writeButton);
        root.Controls.Add(actions);
        return root;
    }

    private GroupBox BuildImageGroup()
    {
        var group = NewGroup("1. qbtOS image");
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 2, AutoSize = true };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        layout.Controls.Add(imagePath, 0, 0);
        layout.Controls.Add(browseButton, 1, 0);
        layout.Controls.Add(new Label { Text = "Browse or drop a .img or .img.zst file here.", AutoSize = true, ForeColor = Color.DimGray }, 0, 1);
        group.Controls.Add(layout);
        return group;
    }

    private GroupBox BuildDiskGroup()
    {
        var group = NewGroup("2. Target whole disk");
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 2, AutoSize = true };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        layout.Controls.Add(diskList, 0, 0);
        layout.Controls.Add(refreshButton, 1, 0);
        layout.Controls.Add(diskDetails, 0, 1);
        layout.SetColumnSpan(diskDetails, 2);
        group.Controls.Add(layout);
        return group;
    }

    private GroupBox BuildDataGroup()
    {
        var group = NewGroup("3. Data storage");
        var layout = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, WrapContents = true };
        layout.Controls.Add(createData);
        layout.Controls.Add(maximumData);
        layout.Controls.Add(new Label { Text = "Size (GiB):", AutoSize = true, Margin = new Padding(14, 7, 3, 0) });
        layout.Controls.Add(dataSize);
        layout.Controls.Add(new Label { Text = "Filesystem:", AutoSize = true, Margin = new Padding(14, 7, 3, 0) });
        layout.Controls.Add(fileSystem);
        group.Controls.Add(layout);
        return group;
    }

    private GroupBox BuildStatusGroup()
    {
        var group = NewGroup("Status");
        group.Dock = DockStyle.Fill;
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 3, ColumnCount = 1 };
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.Controls.Add(status);
        layout.Controls.Add(progress);
        layout.Controls.Add(log);
        group.Controls.Add(layout);
        return group;
    }

    private static GroupBox NewGroup(string title) => new() {
        Text = title, Dock = DockStyle.Top, AutoSize = true, Padding = new Padding(10), Margin = new Padding(3, 5, 3, 5)
    };

    private void BrowseForImage(object? sender, EventArgs e)
    {
        using var dialog = new OpenFileDialog {
            Title = "Select qbtOS image",
            Filter = "qbtOS images (*.img;*.img.zst)|*.img;*.img.zst|All files (*.*)|*.*",
            CheckFileExists = true
        };
        if (File.Exists(imagePath.Text)) dialog.InitialDirectory = Path.GetDirectoryName(imagePath.Text);
        if (dialog.ShowDialog(this) == DialogResult.OK) imagePath.Text = dialog.FileName;
    }

    private static bool IsSupportedImage(string path) =>
        path.EndsWith(".img", StringComparison.OrdinalIgnoreCase) ||
        path.EndsWith(".img.zst", StringComparison.OrdinalIgnoreCase);

    private void ImageDragEnter(object? sender, DragEventArgs e)
    {
        var files = e.Data?.GetData(DataFormats.FileDrop) as string[];
        e.Effect = files is { Length: 1 } && File.Exists(files[0]) && IsSupportedImage(files[0])
            ? DragDropEffects.Copy : DragDropEffects.None;
    }

    private void ImageDragDrop(object? sender, DragEventArgs e)
    {
        var files = e.Data?.GetData(DataFormats.FileDrop) as string[];
        if (files is { Length: 1 } && IsSupportedImage(files[0])) imagePath.Text = Path.GetFullPath(files[0]);
    }

    private async Task RefreshDisksAsync()
    {
        SetBusy(true, "Refreshing disks...");
        try
        {
            var result = await RunPowerShellAsync(["-File", backendPath, "-ListDisks"], null);
            if (result.ExitCode != 0) throw new InvalidOperationException(result.Error.Trim());
            var disks = JsonSerializer.Deserialize<List<DiskTarget>>(result.Output) ?? [];
            diskList.DataSource = disks;
            diskList.DisplayMember = nameof(DiskTarget.DisplayName);
            status.Text = disks.Count == 0 ? "No non-system disks were found." : $"Found {disks.Count} non-system disk(s).";
        }
        catch (Exception exception)
        {
            diskList.DataSource = null;
            status.Text = "Disk refresh failed.";
            MessageBox.Show(this, exception.Message, "Could not list disks", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally { SetBusy(false); }
    }

    private void UpdateDiskDetails()
    {
        diskDetails.Text = diskList.SelectedItem is not DiskTarget disk
            ? "Select a whole disk. Windows boot/system disks are excluded."
            : $"PhysicalDrive{disk.Number} | {disk.SizeLabel} | Bus: {disk.BusType} | Serial: {ValueOrUnknown(disk.SerialNumber)} | Volumes: {string.Join(", ", disk.Volumes ?? [])}";
    }

    private void UpdateDataControls()
    {
        maximumData.Enabled = createData.Checked && !isBusy;
        dataSize.Enabled = createData.Checked && !maximumData.Checked && !isBusy;
        fileSystem.Enabled = createData.Checked && !isBusy;
    }

    private async Task StartWriteAsync()
    {
        if (!File.Exists(imagePath.Text) || !IsSupportedImage(imagePath.Text))
        {
            MessageBox.Show(this, "Select an existing .img or .img.zst file.", "Invalid image", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        if (diskList.SelectedItem is not DiskTarget disk)
        {
            MessageBox.Show(this, "Select a target whole disk.", "No target", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        var dataDescription = !createData.Checked ? "No QBTOS_DATA partition" :
            maximumData.Checked ? $"Maximum available QBTOS_DATA ({SelectedFileSystem()})" :
            $"{dataSize.Value} GiB QBTOS_DATA ({SelectedFileSystem()})";
        using var confirmation = new EraseConfirmationDialog(
            $"PhysicalDrive{disk.Number} — {disk.SizeLabel} — {disk.FriendlyName}",
            $"Bus: {disk.BusType}    Serial: {ValueOrUnknown(disk.SerialNumber)}",
            imagePath.Text,
            dataDescription);
        if (confirmation.ShowDialog(this) != DialogResult.OK) return;

        var arguments = new List<string> {
            "-File", backendPath,
            "-Image", Path.GetFullPath(imagePath.Text),
            "-DiskNumber", disk.Number.ToString(CultureInfo.InvariantCulture),
            "-DataFileSystem", SelectedFileSystem(),
            "-Confirmation", "ERASE",
            "-ExpectedDiskSize", disk.Size.ToString(CultureInfo.InvariantCulture),
            "-ExpectedDiskBusType", disk.BusType,
            "-ExpectedDiskFriendlyName", disk.FriendlyName
        };
        if (!string.IsNullOrWhiteSpace(disk.SerialNumber)) arguments.AddRange(["-ExpectedDiskSerial", disk.SerialNumber.Trim()]);
        if (!createData.Checked) arguments.AddRange(["-DataGiB", "0"]);
        else if (maximumData.Checked) arguments.Add("-UseMaximumData");
        else arguments.AddRange(["-DataGiB", decimal.ToUInt64(dataSize.Value).ToString(CultureInfo.InvariantCulture)]);

        log.Clear();
        progress.Value = 0;
        SetBusy(true, "Preparing and validating the image...");
        try
        {
            var result = await RunPowerShellAsync(arguments, HandleBackendLine);
            if (result.ExitCode != 0) throw new InvalidOperationException(result.Error.Trim().Length > 0 ? result.Error.Trim() : "The imager exited with an error.");
            progress.Value = 100;
            status.Text = "Complete. Use Safely Remove Hardware before removing the device.";
            MessageBox.Show(this, status.Text, "qbtOS image written", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception exception)
        {
            status.Text = "Imaging failed. Review the log; the error was not ignored.";
            AppendLog(exception.Message);
            MessageBox.Show(this, exception.Message, "qbtOS Imager failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally { SetBusy(false); }
    }

    private void HandleBackendLine(string line)
    {
        if (line.StartsWith("QBTOS_PROGRESS|", StringComparison.Ordinal))
        {
            var parts = line.Split('|');
            if (parts.Length == 3 && int.TryParse(parts[2], out var value))
            {
                progress.Value = Math.Clamp(value, 0, 100);
                status.Text = parts[1] == "verify" ? $"Verifying image... {value}%" : $"Writing image... {value}%";
            }
            return;
        }
        if (line.StartsWith("QBTOS_SUCCESS|", StringComparison.Ordinal)) status.Text = "Image write and verification completed.";
        AppendLog(line);
    }

    private async Task<ProcessResult> RunPowerShellAsync(IEnumerable<string> arguments, Action<string>? outputHandler)
    {
        var start = new ProcessStartInfo {
            FileName = Path.Combine(Environment.SystemDirectory, "WindowsPowerShell", "v1.0", "powershell.exe"),
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        start.ArgumentList.Add("-NoLogo");
        start.ArgumentList.Add("-NoProfile");
        start.ArgumentList.Add("-NonInteractive");
        foreach (var argument in arguments) start.ArgumentList.Add(argument);

        using var process = new Process { StartInfo = start, EnableRaisingEvents = true };
        activeProcess = process;
        if (!process.Start()) throw new InvalidOperationException("Could not start Windows PowerShell.");

        var errors = new StringBuilder();
        var output = new StringBuilder();
        var outputTask = ReadLinesAsync(process.StandardOutput, line => {
            output.AppendLine(line);
            if (outputHandler is not null) BeginInvoke(() => outputHandler(line));
        });
        var errorTask = ReadLinesAsync(process.StandardError, line => {
            errors.AppendLine(line);
            if (outputHandler is not null) BeginInvoke(() => AppendLog(line));
        });
        await Task.WhenAll(process.WaitForExitAsync(), outputTask, errorTask);
        activeProcess = null;
        return new ProcessResult(process.ExitCode, output.ToString(), errors.ToString());
    }

    private static async Task ReadLinesAsync(StreamReader reader, Action<string> handler)
    {
        while (await reader.ReadLineAsync() is { } line) handler(line);
    }

    private void SetBusy(bool busy, string? message = null)
    {
        isBusy = busy;
        browseButton.Enabled = !busy;
        imagePath.Enabled = !busy;
        diskList.Enabled = !busy;
        refreshButton.Enabled = !busy;
        createData.Enabled = !busy;
        writeButton.Enabled = !busy;
        UpdateDataControls();
        if (message is not null) status.Text = message;
    }

    private void AppendLog(string value)
    {
        if (string.IsNullOrWhiteSpace(value)) return;
        log.AppendText(value.TrimEnd() + Environment.NewLine);
    }

    private string SelectedFileSystem() => fileSystem.SelectedIndex == 1 ? "ext4" : "NTFS";
    private static string ValueOrUnknown(string? value) => string.IsNullOrWhiteSpace(value) ? "(not reported)" : value.Trim();

    private void PreventCloseDuringWrite(object? sender, FormClosingEventArgs e)
    {
        if (activeProcess is null) return;
        e.Cancel = true;
        MessageBox.Show(this, "The window cannot close while a disk operation is running.", "Imaging in progress", MessageBoxButtons.OK, MessageBoxIcon.Warning);
    }

    private sealed record ProcessResult(int ExitCode, string Output, string Error);
}

internal sealed class DiskTarget
{
    public uint Number { get; set; }
    public string FriendlyName { get; set; } = "Unknown disk";
    public string SerialNumber { get; set; } = "";
    public string BusType { get; set; } = "Unknown";
    public ulong Size { get; set; }
    public string SizeLabel { get; set; } = "Unknown size";
    public uint LogicalSectorSize { get; set; }
    public bool IsBoot { get; set; }
    public bool IsSystem { get; set; }
    public string[]? Volumes { get; set; }
    public string DisplayName => $"PhysicalDrive{Number}  {SizeLabel}  {FriendlyName}  ({BusType})";
}
