namespace QbtOs.Imager.Ui;

internal sealed class EraseConfirmationDialog : Form
{
    private readonly TextBox confirmation = new() { Width = 220 };
    private readonly Button eraseButton = new() { Text = "Erase and write", Enabled = false, AutoSize = true };

    public EraseConfirmationDialog(string disk, string identity, string image, string data)
    {
        Text = "Confirm destructive write";
        StartPosition = FormStartPosition.CenterParent;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MinimizeBox = false;
        MaximizeBox = false;
        AutoSize = true;
        AutoSizeMode = AutoSizeMode.GrowAndShrink;
        Padding = new Padding(18);

        var layout = new TableLayoutPanel { AutoSize = true, ColumnCount = 1, RowCount = 8, Dock = DockStyle.Fill };
        layout.Controls.Add(new Label { Text = "DESTROY ALL DATA?", ForeColor = Color.Firebrick, Font = new Font(Font.FontFamily, 14, FontStyle.Bold), AutoSize = true });
        layout.Controls.Add(new Label { Text = "The selected disk and every filesystem on it will be overwritten.", AutoSize = true, MaximumSize = new Size(620, 0), Margin = new Padding(3, 8, 3, 8) });
        layout.Controls.Add(new Label { Text = disk, Font = new Font(Font, FontStyle.Bold), AutoSize = true });
        layout.Controls.Add(new Label { Text = identity, AutoSize = true });
        layout.Controls.Add(new Label { Text = "Image: " + image, AutoSize = true, MaximumSize = new Size(620, 0) });
        layout.Controls.Add(new Label { Text = data, AutoSize = true, Margin = new Padding(3, 2, 3, 10) });
        layout.Controls.Add(new Label { Text = "Type ERASE exactly to continue:", AutoSize = true });
        layout.Controls.Add(confirmation);

        var actions = new FlowLayoutPanel { AutoSize = true, FlowDirection = FlowDirection.RightToLeft, Dock = DockStyle.Fill, Margin = new Padding(0, 12, 0, 0) };
        var cancelButton = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, AutoSize = true };
        eraseButton.DialogResult = DialogResult.OK;
        actions.Controls.Add(eraseButton);
        actions.Controls.Add(cancelButton);
        layout.Controls.Add(actions);

        Controls.Add(layout);
        AcceptButton = eraseButton;
        CancelButton = cancelButton;
        confirmation.TextChanged += (_, _) => eraseButton.Enabled = confirmation.Text == "ERASE";
    }
}
