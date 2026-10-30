import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import '../state.dart';
import 'glass.dart';
import 'home.dart';
import 'login.dart';

ThemeData visitorTheme({Brightness brightness = Brightness.light}) {
  final dark = brightness == Brightness.dark;
  // Fidelity keeps the brand indigo itself as primary (not a muted tone of it).
  final scheme =
      ColorScheme.fromSeed(
        seedColor: brand,
        brightness: brightness,
        dynamicSchemeVariant: DynamicSchemeVariant.fidelity,
      ).copyWith(
        primary: dark ? const Color(0xFFA5B4FC) : brand,
        onPrimary: dark ? const Color(0xFF1E1B4B) : Colors.white,
        primaryContainer: dark
            ? const Color(0xFF312E81)
            : const Color(0xFFE0E7FF),
        onPrimaryContainer: dark
            ? const Color(0xFFE0E7FF)
            : const Color(0xFF3730A3),
      );
  final t = dark ? GlassTokens.dark : GlassTokens.light;
  const radius12 = BorderRadius.all(Radius.circular(14));
  return ThemeData(
    colorScheme: scheme,
    brightness: brightness,
    fontFamily: 'Vazirmatn',
    useMaterial3: true,
    // Pages draw the glass background themselves (GlassPageTransitions).
    scaffoldBackgroundColor: Colors.transparent,
    pageTransitionsTheme: const PageTransitionsTheme(
      builders: {
        TargetPlatform.android: GlassPageTransitions(),
        TargetPlatform.iOS: GlassPageTransitions(),
        TargetPlatform.linux: GlassPageTransitions(),
        TargetPlatform.macOS: GlassPageTransitions(),
        TargetPlatform.windows: GlassPageTransitions(),
      },
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: Colors.transparent,
      surfaceTintColor: Colors.transparent,
      scrolledUnderElevation: 0,
      elevation: 0,
    ),
    // Data sits on an almost opaque surface (glass is for frames only).
    cardTheme: CardThemeData(
      elevation: 0,
      margin: EdgeInsets.zero,
      color: t.surface,
      shadowColor: const Color(0x2E3C328C),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(18)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      border: OutlineInputBorder(
        borderRadius: radius12,
        borderSide: BorderSide(color: brand.withValues(alpha: .18)),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: radius12,
        borderSide: BorderSide(color: brand.withValues(alpha: .18)),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: radius12,
        borderSide: BorderSide(color: scheme.primary, width: 2),
      ),
      filled: true,
      fillColor: t.surface,
      prefixIconColor: scheme.primary,
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        shape: const RoundedRectangleBorder(borderRadius: radius12),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        shape: const RoundedRectangleBorder(borderRadius: radius12),
        backgroundColor: t.surface.withValues(alpha: .6),
      ),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: SegmentedButton.styleFrom(
        backgroundColor: t.glass,
        selectedBackgroundColor: scheme.primary,
        selectedForegroundColor: scheme.onPrimary,
        side: BorderSide(color: t.border),
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: Colors.transparent,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      height: 66,
      indicatorColor: brand.withValues(alpha: dark ? .35 : .14),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: dark ? const Color(0xF51A1C38) : const Color(0xF5FFFFFF),
      surfaceTintColor: Colors.transparent,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(24)),
      ),
    ),
    bottomSheetTheme: const BottomSheetThemeData(
      backgroundColor: Colors.transparent,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
    ),
    snackBarTheme: const SnackBarThemeData(behavior: SnackBarBehavior.floating),
  );
}

class VisitorApp extends StatelessWidget {
  const VisitorApp({super.key, required this.state});
  final AppState state;

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<bool>(
      valueListenable: state.liteMode,
      builder: (context, lite, _) => MaterialApp(
        title: 'NEXTCAM ویزیتور',
        debugShowCheckedModeBanner: false,
        locale: const Locale('fa', 'IR'),
        supportedLocales: const [Locale('fa', 'IR')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        theme: visitorTheme(),
        darkTheme: visitorTheme(brightness: Brightness.dark),
        builder: (context, child) =>
            GlassMode(lite: lite, child: child ?? const SizedBox()),
        home: ListenableBuilder(
          listenable: state,
          builder: (context, _) => state.signedIn
              ? HomeScreen(state: state)
              : LoginScreen(state: state),
        ),
      ),
    );
  }
}
