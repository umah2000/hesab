import 'package:flutter/material.dart';

import '../api.dart';
import '../state.dart';
import '../tokens.dart';
import 'glass.dart';

String _networkMessage() =>
    'سرور در دسترس نیست؛ اینترنت، نشانی و پورت سرور را بررسی کنید';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key, required this.state});
  final AppState state;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _user = TextEditingController();
  final _pass = TextEditingController();
  bool _remember = true;
  bool _hide = true;
  bool _busy = false;
  String? _error;

  ConnectionSettings? get _saved => widget.state.settings;

  @override
  void initState() {
    super.initState();
    final c = _saved;
    if (c != null) {
      _user.text = c.username;
      _pass.text = c.password ?? '';
      _remember = c.remember;
    }
  }

  @override
  void dispose() {
    _user.dispose();
    _pass.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final c = _saved;
    if (c == null || c.host.isEmpty) {
      await _openSettings();
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.state.login(
        ConnectionSettings(
          host: c.host,
          port: c.port,
          username: _user.text.trim(),
          password: _pass.text,
          remember: _remember,
        ),
      );
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } on NetworkException {
      setState(() => _error = _networkMessage());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _openSettings() async {
    await showConnectionSettings(context, widget.state);
    if (!mounted) return;
    final c = _saved;
    setState(() {
      if (c != null) {
        _user.text = c.username;
        _pass.text = c.password ?? _pass.text;
        _remember = c.remember;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final c = _saved;
    final soft = t.colorScheme.onSurfaceVariant;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Center(
                    child: GlassPanel(
                      radius: const BorderRadius.all(Radius.circular(24)),
                      child: SizedBox.square(
                        dimension: 76,
                        child: Icon(
                          Icons.storefront_rounded,
                          size: 40,
                          color: t.colorScheme.primary,
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 14),
                  Text(
                    'NEXTCAM ویزیتور',
                    textAlign: TextAlign.center,
                    style: t.textTheme.headlineSmall?.copyWith(
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    'سفارش‌گیری از مشتریان، حتی بدون اینترنت',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: soft),
                  ),
                  if (widget.state.signedOut) ...[
                    const SizedBox(height: 16),
                    const Align(
                      child: StatusPill(
                        icon: Icons.info_rounded,
                        label: 'نشست پایان یافت؛ سفارش‌های ارسال‌نشده روی گوشی‌اند',
                        color: StatusPill.warning,
                      ),
                    ),
                  ],
                  const SizedBox(height: 22),
                  GlassPanel(
                    padding: const EdgeInsets.all(18),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        TextField(
                          controller: _user,
                          textDirection: TextDirection.ltr,
                          autocorrect: false,
                          decoration: const InputDecoration(
                            labelText: 'نام کاربری',
                            prefixIcon: Icon(Icons.person_rounded),
                          ),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: _pass,
                          obscureText: _hide,
                          textDirection: TextDirection.ltr,
                          onSubmitted: (_) => _submit(),
                          decoration: InputDecoration(
                            labelText: 'رمز عبور',
                            prefixIcon: const Icon(Icons.lock_rounded),
                            suffixIcon: IconButton(
                              tooltip: _hide ? 'نمایش رمز' : 'پنهان کردن رمز',
                              onPressed: () => setState(() => _hide = !_hide),
                              icon: Icon(
                                _hide
                                    ? Icons.visibility_rounded
                                    : Icons.visibility_off_rounded,
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(height: 4),
                        CheckboxListTile(
                          value: _remember,
                          onChanged: (v) => setState(() => _remember = v!),
                          contentPadding: EdgeInsets.zero,
                          dense: true,
                          controlAffinity: ListTileControlAffinity.leading,
                          title: const Text('مرا در این گوشی به خاطر بسپار'),
                        ),
                        if (_error != null) ...[
                          _ErrorLine(_error!),
                          const SizedBox(height: 10),
                        ],
                        BrandButton(
                          label: 'ورود',
                          busy: _busy,
                          onPressed: _submit,
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 14),
                  _SettingsChip(settings: c, onTap: _openSettings),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _SettingsChip extends StatelessWidget {
  const _SettingsChip({required this.settings, required this.onTap});
  final ConnectionSettings? settings;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final c = settings;
    final has = c != null && c.host.isNotEmpty;
    return GlassPanel(
      radius: const BorderRadius.all(Radius.circular(18)),
      child: Material(
        type: MaterialType.transparency,
        child: InkWell(
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            child: Row(
              children: [
                Icon(Icons.dns_rounded, color: t.colorScheme.primary),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'تنظیمات اتصال',
                        style: TextStyle(fontWeight: FontWeight.w700),
                      ),
                      Text(
                        has ? c.label : 'نشانی سرور، پورت، نام کاربری و رمز',
                        textDirection: has ? TextDirection.ltr : null,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontSize: 12,
                          color: t.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                has
                    ? const StatusPill(
                        icon: Icons.check_rounded,
                        label: 'ذخیره شده',
                        color: StatusPill.ok,
                      )
                    : const StatusPill(
                        icon: Icons.settings_rounded,
                        label: 'تنظیم نشده',
                        color: StatusPill.warning,
                      ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ErrorLine extends StatelessWidget {
  const _ErrorLine(this.message);
  final String message;

  @override
  Widget build(BuildContext context) {
    final color = Theme.of(context).colorScheme.error;
    return Row(
      children: [
        Icon(Icons.error_rounded, color: color, size: 18),
        const SizedBox(width: 6),
        Expanded(
          child: Text(message, style: TextStyle(color: color)),
        ),
      ],
    );
  }
}

/// «تنظیمات اتصال»: server, port, user and password; saved on the phone (Android
/// Keystore) after a successful sign-in, so the app connects by itself next time.
Future<void> showConnectionSettings(BuildContext context, AppState state) =>
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => ConnectionSheet(state: state),
    );

class ConnectionSheet extends StatefulWidget {
  const ConnectionSheet({super.key, required this.state});
  final AppState state;

  @override
  State<ConnectionSheet> createState() => _ConnectionSheetState();
}

class _ConnectionSheetState extends State<ConnectionSheet> {
  final _host = TextEditingController();
  final _port = TextEditingController();
  final _user = TextEditingController();
  final _pass = TextEditingController();
  bool _remember = true;
  bool _hide = true;
  bool _busy = false;
  String? _error;
  String? _ok;

  @override
  void initState() {
    super.initState();
    final c = widget.state.settings;
    if (c != null) {
      _host.text = c.host;
      _port.text = c.port == null ? '' : '${c.port}';
      _user.text = c.username;
      _pass.text = c.password ?? '';
      _remember = c.remember;
    }
  }

  @override
  void dispose() {
    for (final c in [_host, _port, _user, _pass]) {
      c.dispose();
    }
    super.dispose();
  }

  ConnectionSettings _read() {
    var host = _host.text.trim();
    // An address typed with its scheme or path keeps only the host part here.
    final uri = Uri.tryParse(host.contains('://') ? host : 'https://$host');
    if (uri != null && uri.host.isNotEmpty) host = uri.host;
    final port =
        parsePort(_port.text) ?? (uri != null && uri.hasPort ? uri.port : null);
    return ConnectionSettings(
      host: host,
      port: port,
      username: _user.text.trim(),
      password: _pass.text,
      remember: _remember,
    );
  }

  Future<void> _run(Future<void> Function(ConnectionSettings c) action) async {
    setState(() {
      _busy = true;
      _error = null;
      _ok = null;
    });
    try {
      await action(_read());
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } on NetworkException {
      setState(() => _error = _networkMessage());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _test() => _run((c) async {
    await widget.state.testConnection(c);
    final secure = widget.state.serverOf(c).startsWith('https://');
    setState(
      () => _ok = secure ? 'اتصال برقرار است · HTTPS' : 'اتصال برقرار است',
    );
  });

  Future<void> _save() => _run((c) async {
    if (c.username.isEmpty || (c.password ?? '').isEmpty) {
      throw ApiException(0, 'input', 'نام کاربری و رمز عبور را وارد کنید');
    }
    final nav = Navigator.of(context);
    await widget.state.login(c);
    nav.pop();
  });

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final bottom = MediaQuery.viewInsetsOf(context).bottom;
    return Padding(
      padding: EdgeInsets.only(bottom: bottom),
      child: GlassPanel(
        strong: true,
        radius: const BorderRadius.vertical(top: Radius.circular(30)),
        padding: const EdgeInsets.fromLTRB(20, 10, 20, 22),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Center(
                child: Container(
                  width: 44,
                  height: 5,
                  margin: const EdgeInsets.only(bottom: 14),
                  decoration: BoxDecoration(
                    color: t.colorScheme.onSurface.withValues(alpha: .2),
                    borderRadius: BorderRadius.circular(3),
                  ),
                ),
              ),
              Row(
                children: [
                  Icon(Icons.dns_rounded, color: t.colorScheme.primary),
                  const SizedBox(width: 8),
                  Text(
                    'تنظیمات اتصال',
                    style: t.textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              Text(
                'یک بار وارد کنید؛ دفعه‌های بعد اپ خودش وصل می‌شود.',
                style: TextStyle(
                  fontSize: 12,
                  color: t.colorScheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: 16),
              Row(
                children: [
                  Expanded(
                    flex: 2,
                    child: TextField(
                      controller: _host,
                      textDirection: TextDirection.ltr,
                      keyboardType: TextInputType.url,
                      autocorrect: false,
                      decoration: const InputDecoration(
                        labelText: 'نشانی سرور',
                        hintText: 'erp.example.ir',
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: TextField(
                      controller: _port,
                      textDirection: TextDirection.ltr,
                      keyboardType: TextInputType.number,
                      decoration: const InputDecoration(
                        labelText: 'پورت',
                        hintText: '443',
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _user,
                textDirection: TextDirection.ltr,
                autocorrect: false,
                decoration: const InputDecoration(
                  labelText: 'نام کاربری',
                  prefixIcon: Icon(Icons.person_rounded),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _pass,
                obscureText: _hide,
                textDirection: TextDirection.ltr,
                decoration: InputDecoration(
                  labelText: 'رمز عبور',
                  prefixIcon: const Icon(Icons.lock_rounded),
                  suffixIcon: IconButton(
                    tooltip: _hide ? 'نمایش رمز' : 'پنهان کردن رمز',
                    onPressed: () => setState(() => _hide = !_hide),
                    icon: Icon(
                      _hide
                          ? Icons.visibility_rounded
                          : Icons.visibility_off_rounded,
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Card(
                child: SwitchListTile(
                  value: _remember,
                  onChanged: (v) => setState(() => _remember = v),
                  shape: const RoundedRectangleBorder(
                    borderRadius: BorderRadius.all(Radius.circular(18)),
                  ),
                  title: const Text('ذخیره در گوشی'),
                  subtitle: Text(
                    _remember
                        ? 'رمزنگاری‌شده در Keystore اندروید؛ ورود خودکار'
                        : 'رمز ذخیره نمی‌شود؛ پس از پایان نشست دوباره وارد شوید',
                    style: const TextStyle(fontSize: 11),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              if (_ok != null)
                Align(
                  alignment: AlignmentDirectional.centerStart,
                  child: StatusPill(
                    icon: Icons.check_rounded,
                    label: _ok!,
                    color: StatusPill.ok,
                  ),
                ),
              if (_error != null) _ErrorLine(_error!),
              if (_ok != null || _error != null) const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: SizedBox(
                      height: 52,
                      child: OutlinedButton(
                        onPressed: _busy ? null : _test,
                        child: const Text(
                          'آزمایش اتصال',
                          style: TextStyle(fontWeight: FontWeight.w700),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: BrandButton(
                      label: 'ذخیره و ورود',
                      busy: _busy,
                      onPressed: _save,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
