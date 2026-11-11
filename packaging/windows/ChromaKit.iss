; Build.ps1 supplies the project version and the PyInstaller bundle.
[Setup]
AppId={{40777713-B630-4928-8559-081DD165B58F}
AppName=ChromaKit
AppVersion={#AppVersion}
AppPublisher=ChromaKit contributors
AppPublisherURL=https://github.com/aalto-ema/chromakit
AppSupportURL=https://github.com/aalto-ema/chromakit/issues
DefaultDirName={localappdata}\Programs\ChromaKit
DefaultGroupName=ChromaKit
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.17763
UninstallDisplayIcon={app}\ChromaKit.exe
OutputBaseFilename=ChromaKit-{#AppVersion}-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\..\LICENSE

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ChromaKit"; Filename: "{app}\ChromaKit.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\ChromaKit"; Filename: "{app}\ChromaKit.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\ChromaKit.exe"; Description: "Launch ChromaKit"; Flags: nowait postinstall skipifsilent
