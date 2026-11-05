; NEXTCAM ERP — graphical setup.exe for the shop's Windows server and register PCs (Inno Setup 6).
;
; The first page asks what this PC is:
;   - server: the program, database, backups and services (install.ps1 / upgrade.ps1);
;   - register (client): the Device Agent — receipt printer, cash drawer and offline
;     selling — paired with the server, and a desktop shortcut to the register page
;     (install-agent.ps1).
;
; Build on Windows:  powershell -ExecutionPolicy Bypass -File deploy\windows\setup\build-setup.ps1
; (docs/install/windows-installer.md, «ساخت setup.exe»).
;
; The wizard only collects answers. The installation itself is deploy\windows\install.ps1
; (or upgrade.ps1 when NEXTCAM is already installed in the chosen folder), the same
; scripts used by hand. Answers reach the script as NEXTCAM_INSTALL_* environment
; variables of the setup process: no password is written to a file or a command line.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef PackageDir
  #define PackageDir "..\..\..\dist\nextcam-" + AppVersion
#endif
#define RedistDir SourcePath + "redist"

[Setup]
AppId={{1FA7B6A4-9868-4E54-8F47-EA89CCE915E9}
AppName=NEXTCAM ERP
AppVersion={#AppVersion}
AppPublisher=NEXTCAM
DefaultDirName=C:\nextcam
DisableProgramGroupPage=yes
DisableDirPage=no
UsePreviousAppDir=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
OutputDir=..\..\..\dist
OutputBaseFilename=nextcam-setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
UninstallDisplayName=NEXTCAM ERP
SetupLogging=yes
#ifexist SourcePath + "Farsi.isl"
ShowLanguageDialog=no
#endif

[Languages]
#ifexist SourcePath + "Farsi.isl"
Name: "fa"; MessagesFile: "Farsi.isl"
#else
Name: "en"; MessagesFile: "compiler:Default.isl"
#endif

[Files]
; The release package (tools/release/build_release.py) — used once, then deleted.
Source: "{#PackageDir}\*"; DestDir: "{tmp}\package"; Flags: recursesubdirs createallsubdirs ignoreversion
; Scripts kept for upgrade and uninstall.
Source: "{#PackageDir}\deploy\windows\*.ps1"; DestDir: "{app}\setup"; Flags: ignoreversion
; Prerequisites, installed only when missing (put them in deploy\windows\setup\redist).
#ifexist RedistDir + "\python-amd64.exe"
Source: "redist\python-amd64.exe"; Flags: dontcopy
#endif
#ifexist RedistDir + "\msodbcsql.msi"
Source: "redist\msodbcsql.msi"; Flags: dontcopy
#endif
#ifexist RedistDir + "\vc_redist.x64.exe"
Source: "redist\vc_redist.x64.exe"; Flags: dontcopy
#endif

[INI]
; Register: the register page opens from the local agent, so it keeps selling offline.
Filename: "{commondesktop}\NEXTCAM Register.url"; Section: "InternetShortcut"; Key: "URL"; \
  String: "http://127.0.0.1:47616/pos"; Check: IsClient

[UninstallDelete]
Type: files; Name: "{commondesktop}\NEXTCAM Register.url"

[UninstallRun]
; Server: program, tasks and firewall rules go; the database, backups and settings stay.
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\setup\uninstall.ps1"" -Root ""{app}"""; \
  Flags: runhidden waituntilterminated; RunOnceId: "NextcamUninstall"; Check: not IsClient
; Register: the agent service goes; its settings and unsent offline sales stay.
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\setup\uninstall-agent.ps1"" -Root ""{app}"""; \
  Flags: runhidden waituntilterminated; RunOnceId: "NextcamAgentUninstall"; Check: IsClient

[Code]
function SetEnvironmentVariable(lpName: string; lpValue: string): BOOL;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

var
  ShopPage, SqlPage, SqlAdminPage, AdminPage, ClientPage: TInputQueryWizardPage;
  DbModePage, ModePage: TInputOptionWizardPage;
  FolderPage: TInputDirWizardPage;
  ResultPage: TOutputMsgMemoWizardPage;
  Upgrade: Boolean;
  Failed: Boolean;

function IsClient: Boolean;
begin
  Result := (ModePage <> nil) and (ModePage.SelectedValueIndex = 1);
end;

function IsUpgrade: Boolean;
begin
  if IsClient then
    Result := FileExists(AddBackslash(WizardDirValue) + 'agent-venv\Scripts\python.exe')
  else
    Result := DirExists(AddBackslash(WizardDirValue) + 'current');
end;

procedure InitializeWizard;
begin
  ModePage := CreateInputOptionPage(wpWelcome,
    'نوع نصب', 'این رایانه کدام است؟',
    'یک بار روی سرور فروشگاه «سرور» را نصب کنید؛ روی هر رایانه‌ی صندوق «صندوق».', True, False);
  ModePage.Add('سرور: برنامه، دیتابیس، پشتیبان‌گیری و سرویس‌ها');
  ModePage.Add('صندوق (کلاینت): چاپ فیش، کشوی پول و فروش آفلاین؛ وصل به سرور');
  ModePage.SelectedValueIndex := 0;

  ClientPage := CreateInputQueryPage(wpSelectDir,
    'اتصال صندوق', 'نشانی سرور و کد جفت‌سازی',
    'نشانی همان است که صندوق‌ها با آن وارد برنامه می‌شوند (مثلاً http://192.168.1.10:8080). ' +
    'کد را در برنامه از «دستگاه‌های صندوق ← دستگاه جدید» بگیرید؛ ۱۵ دقیقه اعتبار دارد و یک بار مصرف است.');
  ClientPage.Add('نشانی سرور NEXTCAM:', False);
  ClientPage.Add('کد جفت‌سازی:', False);
  ClientPage.Values[0] := 'http://';

  ShopPage := CreateInputQueryPage(ClientPage.ID,
    'فروشگاه', 'نام فروشگاه و درگاه برنامه',
    'نام فروشگاه روی فیش و صفحه‌ی ورود دیده می‌شود. درگاه (port) همان است که صندوق‌ها با آن وصل می‌شوند.');
  ShopPage.Add('نام فروشگاه / سازمان:', False);
  ShopPage.Add('درگاه برنامه (port):', False);
  ShopPage.Values[1] := '8080';

  SqlPage := CreateInputQueryPage(ShopPage.ID,
    'SQL Server', 'دیتابیس و کاربر برنامه',
    'نام SQL Server (مثلاً localhost یا .\SQLEXPRESS)، نام دیتابیس و کاربر SQL که برنامه با آن کار می‌کند. ' +
    'نام دیتابیس و کاربر فقط حروف انگلیسی، عدد و _ . رمز حداقل ۸ کاراکتر با حرف بزرگ، کوچک و عدد.');
  SqlPage.Add('SQL Server:', False);
  SqlPage.Add('نام دیتابیس:', False);
  SqlPage.Add('کاربر SQL برنامه:', False);
  SqlPage.Add('رمز کاربر SQL:', True);
  SqlPage.Add('تکرار رمز:', True);
  SqlPage.Values[0] := 'localhost';
  SqlPage.Values[1] := 'nextcam';
  SqlPage.Values[2] := 'nextcam_app';

  DbModePage := CreateInputOptionPage(SqlPage.ID,
    'ساخت دیتابیس', 'دیتابیس و کاربر SQL ساخته شوند؟', '', True, False);
  DbModePage.Add('بله؛ نصب‌کننده دیتابیس و کاربر را بسازد (پیشنهادی)');
  DbModePage.Add('نه؛ قبلاً با create-database.sql ساخته‌ام');
  DbModePage.SelectedValueIndex := 0;

  SqlAdminPage := CreateInputQueryPage(DbModePage.ID,
    'مدیر SQL Server', 'حساب مدیر SQL Server برای ساخت دیتابیس',
    'خالی بگذارید تا با همین حساب ویندوز (Windows Authentication) وصل شود؛ ' +
    'یا یک حساب sysadmin مثل sa وارد کنید. این رمز ذخیره نمی‌شود.');
  SqlAdminPage.Add('کاربر مدیر SQL (خالی = ویندوز):', False);
  SqlAdminPage.Add('رمز مدیر SQL:', True);

  AdminPage := CreateInputQueryPage(SqlAdminPage.ID,
    'مدیر برنامه', 'کاربر مدیر سیستم NEXTCAM',
    'با این کاربر وارد برنامه می‌شوید. رمز حداقل ۸ کاراکتر و شامل حرف و عدد.');
  AdminPage.Add('نام کاربری:', False);
  AdminPage.Add('رمز:', True);
  AdminPage.Add('تکرار رمز:', True);
  AdminPage.Values[0] := 'admin';

  FolderPage := CreateInputDirPage(AdminPage.ID,
    'پشتیبان‌گیری', 'پوشه‌های پشتیبان',
    'پشتیبان روزانه در پوشه‌ی اول ذخیره می‌شود. پوشه‌ی دوم (اختیاری، مثلاً دیسک USB یا NAS) نسخه‌ی رمزنگاری‌شده را می‌گیرد. ' +
    'بهتر است پوشه‌ی اول روی دیسکی غیر از دیسک ویندوز باشد.', False, '');
  FolderPage.Add('پوشه‌ی پشتیبان:');
  FolderPage.Add('مقصد دوم (اختیاری؛ خالی بگذارید اگر ندارید):');
  FolderPage.Values[0] := 'D:\nextcam-backup';

  ResultPage := CreateOutputMsgMemoPage(wpInstalling,
    'نتیجه‌ی نصب', 'این اطلاعات را یادداشت کنید', '', '');
end;

var
  ModeGuessed: Boolean;

{ A PC that already has only the register agent is offered «register» again. }
procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = ModePage.ID) and not ModeGuessed then
  begin
    ModeGuessed := True;
    if FileExists(AddBackslash(WizardDirValue) + 'agent-venv\Scripts\python.exe') and
       not DirExists(AddBackslash(WizardDirValue) + 'current') then
      ModePage.SelectedValueIndex := 1;
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Upgrade := IsUpgrade;
  Result := False;
  if IsClient and ((PageID = ShopPage.ID) or (PageID = SqlPage.ID) or (PageID = DbModePage.ID) or
     (PageID = SqlAdminPage.ID) or (PageID = AdminPage.ID) or (PageID = FolderPage.ID)) then
  begin
    Result := True;
    Exit;
  end;
  if (PageID = ClientPage.ID) and (not IsClient or Upgrade) then
  begin
    Result := True;
    Exit;
  end;
  if Upgrade and ((PageID = ShopPage.ID) or (PageID = SqlPage.ID) or (PageID = DbModePage.ID) or
     (PageID = SqlAdminPage.ID) or (PageID = AdminPage.ID) or (PageID = FolderPage.ID)) then
    Result := True;
  if (PageID = SqlAdminPage.ID) and (DbModePage.SelectedValueIndex <> 0) then
    Result := True;
end;

function IsName(const S: string): Boolean;
var
  I: Integer;
  C: Char;
begin
  Result := (Length(S) > 0) and (Length(S) <= 64);
  for I := 1 to Length(S) do
  begin
    C := S[I];
    if not (((C >= 'a') and (C <= 'z')) or ((C >= 'A') and (C <= 'Z')) or (C = '_') or
            ((I > 1) and (C >= '0') and (C <= '9'))) then
      Result := False;
  end;
end;

function CharClasses(const S: string; var Letters, Digits, Upper, Lower, Other: Boolean): Integer;
var
  I: Integer;
  C: Char;
begin
  Letters := False; Digits := False; Upper := False; Lower := False; Other := False;
  for I := 1 to Length(S) do
  begin
    C := S[I];
    if (C >= '0') and (C <= '9') then Digits := True
    else if (C >= 'A') and (C <= 'Z') then begin Upper := True; Letters := True; end
    else if (C >= 'a') and (C <= 'z') then begin Lower := True; Letters := True; end
    else if C <> ' ' then begin Other := True; Letters := True; end;
  end;
  Result := 0;
  if Digits then Result := Result + 1;
  if Upper then Result := Result + 1;
  if Lower then Result := Result + 1;
  if Other then Result := Result + 1;
end;

function IsUserName(const S: string): Boolean;
var
  I: Integer;
  C: Char;
begin
  Result := (Length(S) >= 3) and (Length(S) <= 64);
  for I := 1 to Length(S) do
  begin
    C := S[I];
    if not (((C >= 'a') and (C <= 'z')) or ((C >= 'A') and (C <= 'Z')) or ((C >= '0') and (C <= '9')) or
            (C = '_') or (C = '.') or (C = '-')) then
      Result := False;
  end;
end;

function ShowError(const Msg: string): Boolean;
begin
  MsgBox(Msg, mbError, MB_OK);
  Result := False;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  L, D, U, Lo, O: Boolean;
  Port: Integer;
begin
  Result := True;
  if CurPageID = ClientPage.ID then
  begin
    if (Pos('http://', Lowercase(Trim(ClientPage.Values[0]))) <> 1) and
       (Pos('https://', Lowercase(Trim(ClientPage.Values[0]))) <> 1) then
      Result := ShowError('نشانی سرور با http:// یا https:// شروع شود، مثلاً http://192.168.1.10:8080')
    else if Length(Trim(ClientPage.Values[0])) < 12 then
      Result := ShowError('نشانی سرور را کامل وارد کنید.')
    else if Trim(ClientPage.Values[1]) = '' then
      Result := ShowError('کد جفت‌سازی را از «دستگاه‌های صندوق ← دستگاه جدید» در برنامه بگیرید.');
  end
  else if CurPageID = ShopPage.ID then
  begin
    if Trim(ShopPage.Values[0]) = '' then Result := ShowError('نام فروشگاه را وارد کنید.')
    else
    begin
      Port := StrToIntDef(Trim(ShopPage.Values[1]), 0);
      if (Port < 1024) or (Port > 65535) then Result := ShowError('درگاه باید عددی بین ۱۰۲۴ و ۶۵۵۳۵ باشد.');
    end;
  end
  else if CurPageID = SqlPage.ID then
  begin
    if Trim(SqlPage.Values[0]) = '' then Result := ShowError('نام SQL Server را وارد کنید.')
    else if not IsName(SqlPage.Values[1]) then Result := ShowError('نام دیتابیس فقط حروف انگلیسی، عدد و _ (با حرف شروع شود).')
    else if not IsName(SqlPage.Values[2]) then Result := ShowError('نام کاربر SQL فقط حروف انگلیسی، عدد و _ (با حرف شروع شود).')
    else if SqlPage.Values[3] <> SqlPage.Values[4] then Result := ShowError('رمز و تکرار آن یکی نیستند.')
    else if (Length(SqlPage.Values[3]) < 8) or (CharClasses(SqlPage.Values[3], L, D, U, Lo, O) < 3) then
      Result := ShowError('رمز SQL حداقل ۸ کاراکتر و از سه دسته باشد: حرف بزرگ، حرف کوچک، عدد، نماد.');
  end
  else if CurPageID = AdminPage.ID then
  begin
    CharClasses(AdminPage.Values[1], L, D, U, Lo, O);
    if not IsUserName(Trim(AdminPage.Values[0])) then Result := ShowError('نام کاربری مدیر: ۳ تا ۶۴ حرف انگلیسی، عدد، نقطه، خط تیره یا _.')
    else if AdminPage.Values[1] <> AdminPage.Values[2] then Result := ShowError('رمز و تکرار آن یکی نیستند.')
    else if (Length(AdminPage.Values[1]) < 8) or not L or not D then
      Result := ShowError('رمز مدیر حداقل ۸ کاراکتر و شامل حرف و عدد باشد.')
    else if Lowercase(Trim(AdminPage.Values[1])) = Lowercase(Trim(AdminPage.Values[0])) then
      Result := ShowError('رمز نباید با نام کاربری یکسان باشد.');
  end
  else if CurPageID = FolderPage.ID then
  begin
    if Trim(FolderPage.Values[0]) = '' then Result := ShowError('پوشه‌ی پشتیبان را انتخاب کنید.');
  end;
end;

procedure SetEnv(const Name, Value: string);
begin
  SetEnvironmentVariable(Name, Value);
end;

function RunHidden(const FileName, Params: string): Integer;
begin
  if not Exec(FileName, Params, '', SW_HIDE, ewWaitUntilTerminated, Result) then Result := -1;
end;

{ Python 3.13, ODBC Driver 18 and the VC++ runtime, from redist\ when missing. }
procedure InstallPrerequisites;
var
  Code: Integer;
begin
  WizardForm.StatusLabel.Caption := 'بررسی پیش‌نیازها…';
  { The VC++ runtime installer is safe to run again: it exits when a newer one is there. }
  begin
    try
      ExtractTemporaryFile('vc_redist.x64.exe');
      WizardForm.StatusLabel.Caption := 'نصب Visual C++ Runtime…';
      RunHidden(ExpandConstant('{tmp}\vc_redist.x64.exe'), '/install /quiet /norestart');
    except
    end;
  end;
  if not IsClient and not RegKeyExists(HKLM, 'SOFTWARE\ODBC\ODBCINST.INI\ODBC Driver 18 for SQL Server') then
  begin
    try
      ExtractTemporaryFile('msodbcsql.msi');
      WizardForm.StatusLabel.Caption := 'نصب ODBC Driver 18 for SQL Server…';
      Code := RunHidden(ExpandConstant('{sys}\msiexec.exe'),
        '/i "' + ExpandConstant('{tmp}\msodbcsql.msi') + '" /qn IACCEPTMSODBCSQLLICENSETERMS=YES');
    except
      MsgBox('ODBC Driver 18 for SQL Server نصب نیست و در این بسته هم نیست. آن را از سایت مایکروسافت نصب کنید و دوباره نصب را اجرا کنید.', mbError, MB_OK);
    end;
  end;
  if not RegKeyExists(HKLM, 'SOFTWARE\Python\PythonCore\3.13\InstallPath') and
     not RegKeyExists(HKCU, 'SOFTWARE\Python\PythonCore\3.13\InstallPath') then
  begin
    try
      ExtractTemporaryFile('python-amd64.exe');
      WizardForm.StatusLabel.Caption := 'نصب Python 3.13…';
      Code := RunHidden(ExpandConstant('{tmp}\python-amd64.exe'),
        '/quiet InstallAllUsers=1 PrependPath=1 Include_launcher=1 InstallLauncherAllUsers=1 Include_test=0');
    except
      MsgBox('Python 3.13 (64 بیتی) نصب نیست و در این بسته هم نیست. آن را از python.org نصب کنید و دوباره نصب را اجرا کنید.', mbError, MB_OK);
    end;
  end;
end;

procedure ShowResult;
var
  Lines: TArrayOfString;
  I: Integer;
  Text, Url, Key: string;
begin
  Url := '';
  Key := '';
  if LoadStringsFromFile(ExpandConstant('{tmp}\result.txt'), Lines) then
    for I := 0 to GetArrayLength(Lines) - 1 do
    begin
      if Pos('URL=', Lines[I]) = 1 then Url := Copy(Lines[I], 5, Length(Lines[I]));
      if Pos('BACKUP_KEY=', Lines[I]) = 1 then Key := Copy(Lines[I], 12, Length(Lines[I]));
    end;
  DeleteFile(ExpandConstant('{tmp}\result.txt'));
  if IsClient and not Failed then
  begin
    if Upgrade then Text := 'برنامه‌ی صندوق به‌روز شد و دوباره اجرا شد.'
    else Text := 'صندوق نصب و به سرور وصل شد.' + #13#10#13#10 +
         'صندوق را از میانبر «NEXTCAM Register» روی دسکتاپ باز کنید (http://127.0.0.1:47616/pos). ' +
         'با این نشانی، هنگام قطع شبکه هم فروش نقد و کارت ادامه می‌یابد.' + #13#10#13#10 +
         'در برنامه، «دستگاه‌های صندوق» باید این دستگاه را «متصل» نشان دهد؛ «چاپ آزمایشی» را بزنید.';
    ResultPage.RichEditViewer.Lines.Text := Text;
    Exit;
  end;
  if Failed then
    Text := 'نصب کامل نشد. پیام خطا در پنجره‌ی PowerShell نمایش داده شد.' + #13#10 +
            'پس از رفع مشکل، همین setup را دوباره اجرا کنید (دیتابیس و تنظیمات ساخته‌شده حفظ می‌شوند).'
  else if Upgrade then
    Text := 'به‌روزرسانی انجام شد. پیش از آن پشتیبان گرفته شد.' + #13#10 + 'گزارش: ' + ExpandConstant('{app}\logs')
  else
  begin
    Text := 'NEXTCAM نصب شد و در حال اجراست.' + #13#10#13#10 +
            'نشانی برنامه برای صندوق‌ها و مدیران:' + #13#10 + '    ' + Url + #13#10#13#10;
    if Key <> '' then
      Text := Text + 'کلید پشتیبان (حتماً یادداشت کنید و بیرون از این سرور نگه دارید؛ بدون آن پشتیبان رمزنگاری‌شده بازیابی نمی‌شود):' + #13#10 +
              '    ' + Key + #13#10#13#10;
    Text := Text + 'ورود با کاربر «' + AdminPage.Values[0] + '» و رمزی که وارد کردید.' + #13#10 +
            'تنظیمات: ' + ExpandConstant('{app}\config\.env') + ' (فقط مدیران ویندوز)';
  end;
  ResultPage.RichEditViewer.Lines.Text := Text;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
  Script, Params: string;
begin
  if CurStep <> ssPostInstall then Exit;
  Upgrade := IsUpgrade;
  Failed := False;
  InstallPrerequisites;
  SetEnv('NEXTCAM_INSTALL_PAUSE_ON_ERROR', '1');
  SetEnv('NEXTCAM_INSTALL_RESULT', ExpandConstant('{tmp}\result.txt'));
  if IsClient then
  begin
    WizardForm.StatusLabel.Caption := 'نصب برنامه‌ی صندوق (Device Agent) و جفت‌سازی با سرور…';
    Script := ExpandConstant('{tmp}\package\deploy\windows\install-agent.ps1');
    Params := '';
    if not Upgrade then
    begin
      SetEnv('NEXTCAM_INSTALL_SERVER', Trim(ClientPage.Values[0]));
      SetEnv('NEXTCAM_INSTALL_PAIR_CODE', Trim(ClientPage.Values[1]));
    end;
  end
  else if Upgrade then
  begin
    WizardForm.StatusLabel.Caption := 'به‌روزرسانی NEXTCAM (پشتیبان، دیتابیس، بررسی سلامت)…';
    Script := ExpandConstant('{tmp}\package\deploy\windows\upgrade.ps1');
    Params := '';
  end
  else
  begin
    WizardForm.StatusLabel.Caption := 'نصب NEXTCAM (دیتابیس، کاربر مدیر، سرویس‌ها)…';
    Script := ExpandConstant('{tmp}\package\deploy\windows\install.ps1');
    SetEnv('NEXTCAM_INSTALL_ORG', Trim(ShopPage.Values[0]));
    SetEnv('NEXTCAM_INSTALL_PORT', Trim(ShopPage.Values[1]));
    SetEnv('NEXTCAM_INSTALL_SQL_SERVER', Trim(SqlPage.Values[0]));
    SetEnv('NEXTCAM_INSTALL_DATABASE', Trim(SqlPage.Values[1]));
    SetEnv('NEXTCAM_INSTALL_SQL_USER', Trim(SqlPage.Values[2]));
    SetEnv('NEXTCAM_INSTALL_SQL_PASSWORD', SqlPage.Values[3]);
    SetEnv('NEXTCAM_INSTALL_SQL_ADMIN_USER', Trim(SqlAdminPage.Values[0]));
    SetEnv('NEXTCAM_INSTALL_SQL_ADMIN_PASSWORD', SqlAdminPage.Values[1]);
    SetEnv('NEXTCAM_INSTALL_BACKUP_DIR', Trim(FolderPage.Values[0]));
    SetEnv('NEXTCAM_INSTALL_COPY_DIR', Trim(FolderPage.Values[1]));
    SetEnv('NEXTCAM_SETUP_ADMIN_PASSWORD', AdminPage.Values[1]);
    Params := ' -AdminUser "' + Trim(AdminPage.Values[0]) + '"';
    if DbModePage.SelectedValueIndex = 0 then Params := Params + ' -CreateDatabase';
  end;
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
       '-NoProfile -ExecutionPolicy Bypass -File "' + Script + '" -Root "' + ExpandConstant('{app}') + '"' + Params,
       '', SW_SHOWNORMAL, ewWaitUntilTerminated, Code) or (Code <> 0) then
    Failed := True;
  { The secrets leave this process's environment as soon as the script is done. }
  SetEnv('NEXTCAM_INSTALL_SQL_PASSWORD', '');
  SetEnv('NEXTCAM_INSTALL_SQL_ADMIN_PASSWORD', '');
  SetEnv('NEXTCAM_SETUP_ADMIN_PASSWORD', '');
  SetEnv('NEXTCAM_INSTALL_PAIR_CODE', '');
  ShowResult;
end;
