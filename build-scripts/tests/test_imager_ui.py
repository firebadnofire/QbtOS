# SPDX-License-Identifier: GPL-3.0-or-later

import unittest
from pathlib import Path


REPO = Path(__file__).parents[2]
UI = REPO / "build-scripts" / "imager-ui"
BACKEND = REPO / "build-scripts" / "imager.ps1"
BUILD = REPO / "build-scripts" / "build-imager-ui.ps1"
CLEAN = REPO / "build-scripts" / "clean.ps1"


class WindowsImagerUiTests(unittest.TestCase):
    def test_gui_embeds_backend_and_requires_elevation(self):
        project = (UI / "QbtOs.Imager.Ui.csproj").read_text(encoding="utf-8")
        manifest = (UI / "app.manifest").read_text(encoding="utf-8")
        self.assertIn('EmbeddedResource Include="..\\imager.ps1"', project)
        self.assertIn('level="requireAdministrator"', manifest)

    def test_custom_images_support_browse_and_drag_drop(self):
        source = (UI / "MainForm.cs").read_text(encoding="utf-8")
        self.assertIn("AllowDrop = true", source)
        self.assertIn("DataFormats.FileDrop", source)
        self.assertIn('EndsWith(".img"', source)
        self.assertIn('EndsWith(".img.zst"', source)
        self.assertIn("OpenFileDialog", source)

    def test_gui_reconfirms_disk_identity_and_exact_erase(self):
        source = (UI / "MainForm.cs").read_text(encoding="utf-8")
        confirmation = (UI / "EraseConfirmationDialog.cs").read_text(encoding="utf-8")
        backend = BACKEND.read_text(encoding="utf-8")
        for value in ("ExpectedDiskSize", "ExpectedDiskSerial", "ExpectedDiskBusType", "ExpectedDiskFriendlyName"):
            self.assertIn(value, source)
            self.assertIn(value, backend)
        self.assertIn('confirmation.Text == "ERASE"', confirmation)
        self.assertIn("$RequestedConfirmation -ceq 'ERASE'", backend)
        self.assertLess(backend.index("Test-QbtOsImageLayout $resolvedImage"), backend.index("Get-Disk -Number $RequestedDiskNumber"))

    def test_gui_has_progress_and_prevents_unsafe_close(self):
        source = (UI / "MainForm.cs").read_text(encoding="utf-8")
        backend = BACKEND.read_text(encoding="utf-8")
        self.assertIn("QBTOS_PROGRESS|", source)
        self.assertIn("QBTOS_PROGRESS|write|", backend)
        self.assertIn("QBTOS_PROGRESS|verify|", backend)
        self.assertIn("The window cannot close while a disk operation is running.", source)

    def test_build_and_clean_outputs_are_scoped(self):
        build = BUILD.read_text(encoding="utf-8")
        clean = CLEAN.read_text(encoding="utf-8")
        self.assertIn("output\\imager-ui", build)
        self.assertIn("output\\imager-ui-build", build)
        self.assertIn("--self-contained true", build)
        self.assertIn("-p:PublishSingleFile=true", build)
        self.assertIn("StartsWith($repositoryPrefix", clean)
        self.assertIn("Remove-Item -LiteralPath $resolvedTarget", clean)
        self.assertNotIn("Remove-Item $target", clean)


if __name__ == "__main__":
    unittest.main()
