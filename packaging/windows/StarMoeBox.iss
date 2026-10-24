; StarMoe Box（iOS 版）Windows 安装包 —— Inno Setup 6
; 由 packaging\build_windows.ps1 调用：ISCC /DAppVersion=x.y.z packaging\windows\StarMoeBox.iss
; 输入：dist\StarMoeBox\（PyInstaller onedir）  输出：dist\StarMoeBox-Setup.exe
;
; · 按用户安装，不需要管理员权限（装到 %LOCALAPPDATA%\Programs\StarMoe Box）
; · 开始菜单 + 桌面快捷方式
; · 安装时在 HKCU 注册 moe.starmoe.box:// 登录回调协议，卸载时删除
; · 检查 Apple 设备支持（Apple Devices / iTunes），没有就引导去 Microsoft Store 安装

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "StarMoe Box"
#define AppExe "StarMoeBox.exe"
#define Scheme "moe.starmoe.box"
#define RepoUrl "https://github.com/MisakaZhu/starmoe-box-ios"
#define StoreUrl "ms-windows-store://pdp/?ProductId=9NP83LWLPZ9K"
#define StoreWeb "https://apps.microsoft.com/detail/9NP83LWLPZ9K"

[Setup]
AppId={{9E51F65A-69B3-44C2-9DBA-42E47BA4E777}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=StarMoe Box iOS 社区版（非官方）
AppPublisherURL={#RepoUrl}
AppSupportURL={#RepoUrl}/issues
AppUpdatesURL={#RepoUrl}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=StarMoeBox-Setup
SetupIconFile=..\icons\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
LicenseFile=..\..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no
LanguageDetectionMethod=none
CloseApplications=yes
RestartApplications=no

[Languages]
#if FileExists(AddBackslash(CompilerPath) + "Languages\ChineseSimplified.isl")
Name: "zh"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#elif FileExists(AddBackslash(SourcePath) + "ChineseSimplified.isl")
Name: "zh"; MessagesFile: "ChineseSimplified.isl"
#endif
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："

[Files]
Source: "..\..\dist\StarMoeBox\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; 登录回调协议（浏览器授权完成后跳回本程序）
Root: HKCU; Subkey: "Software\Classes\{#Scheme}"; ValueType: string; ValueName: ""; ValueData: "URL:StarMoe Box"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\{#Scheme}"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\{#Scheme}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"",0"
Root: HKCU; Subkey: "Software\Classes\{#Scheme}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""

[Run]
Filename: "{#StoreUrl}"; Description: "打开 Microsoft Store 安装「Apple Devices」（连接 iPhone 必需）"; Flags: postinstall shellexec skipifsilent nowait; Check: NeedAppleSupport
Filename: "{app}\{#AppExe}"; Description: "立即打开 StarMoe Box"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; 只删除程序目录里运行时生成的文件；用户数据（%LOCALAPPDATA%\StarMoeBox：日志、缓存的官方 APK）保留
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
var
  ApplePage: TOutputMsgWizardPage;

{ Apple 设备支持：Microsoft Store 版 Apple Devices / iTunes（含 Apple Mobile Device Support 驱动） }
function AppleSupportInstalled(): Boolean;
begin
  Result :=
    DirExists(ExpandConstant('{localappdata}\Packages\AppleInc.AppleDevices_nzyj5cx40ttqa')) or
    RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\Apple Mobile Device Service') or
    RegKeyExists(HKLM, 'SOFTWARE\Apple Inc.\Apple Mobile Device Support') or
    RegKeyExists(HKLM32, 'SOFTWARE\Apple Inc.\Apple Mobile Device Support');
end;

function NeedAppleSupport(): Boolean;
begin
  Result := not AppleSupportInstalled();
end;

procedure InitializeWizard();
begin
  ApplePage := CreateOutputMsgPage(wpSelectTasks,
    '还需要 Apple 设备支持',
    '没有检测到 Apple Devices 或 iTunes',
    'Windows 需要 Apple 官方的 USB 驱动才能和 iPhone 通信（只需安装一次，免费）。' + #13#10#13#10 +
    '1. 安装完成后，勾选“打开 Microsoft Store 安装「Apple Devices」”；' + #13#10 +
    '2. 在商店里点“获取/安装”；' + #13#10 +
    '3. 装好后打开 StarMoe Box，插上 iPhone 点“开始”。' + #13#10#13#10 +
    '已经装了 iTunes 也可以。也可以稍后在 StarMoe Box 里按提示安装。' + #13#10 +
    '网页版商店地址：{#StoreWeb}');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (ApplePage <> nil) and (PageID = ApplePage.ID) and AppleSupportInstalled();
end;
