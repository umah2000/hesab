import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import '../state.dart';
import 'home.dart';
import 'login.dart';

const brand = Color(0xFF4F46E5);

ThemeData visitorTheme() {
  final scheme = ColorScheme.fromSeed(seedColor: brand);
  return ThemeData(
    colorScheme: scheme,
    fontFamily: 'Vazirmatn',
    useMaterial3: true,
    scaffoldBackgroundColor: const Color(0xFFF5F6FB),
    cardTheme: const CardThemeData(
      elevation: 0,
      margin: EdgeInsets.zero,
      color: Colors.white,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(16)),
      ),
    ),
    inputDecorationTheme: const InputDecorationTheme(
      border: OutlineInputBorder(
        borderRadius: BorderRadius.all(Radius.circular(12)),
      ),
      filled: true,
      fillColor: Colors.white,
    ),
  );
}

class VisitorApp extends StatelessWidget {
  const VisitorApp({super.key, required this.state});
  final AppState state;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'NEXTCAM ویزیتور',
      debugShowCheckedModeBanner: false,
      locale: const Locale('fa', 'IR'),
      supportedLocales: const [Locale('fa', 'IR')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      theme: visitorTheme(),
      home: ListenableBuilder(
        listenable: state,
        builder: (context, _) => state.signedIn
            ? HomeScreen(state: state)
            : LoginScreen(state: state),
      ),
    );
  }
}
