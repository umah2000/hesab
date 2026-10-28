/// «Glass 2026» on the phone (docs/design/README.md): glass only for frames (top bar,
/// sign-in card, sheets, bottom bar); lists and fields stay on an almost opaque
/// surface so they read in sunlight. «حالت سبک» drops the blur for slow phones.
library;

import 'dart:ui';

import 'package:flutter/material.dart';

const brand = Color(0xFF4F46E5);
const brand2 = Color(0xFF7C3AED);

/// Colours of the glass, per brightness.
class GlassTokens {
  const GlassTokens._({
    required this.glass,
    required this.glassStrong,
    required this.border,
    required this.surface,
    required this.background,
    required this.blobs,
  });

  final Color glass;
  final Color glassStrong;
  final Color border;
  final Color surface;
  final List<Color> background;
  final List<Color> blobs;

  static const light = GlassTokens._(
    glass: Color(0x8CFFFFFF),
    glassStrong: Color(0xBDFFFFFF),
    border: Color(0xBFFFFFFF),
    surface: Color(0xEDFFFFFF),
    background: [Color(0xFFEEF0FF), Color(0xFFF6F0FF)],
    blobs: [Color(0xFF818CF8), Color(0xFF60A5FA), Color(0xFFC084FC)],
  );

  static const dark = GlassTokens._(
    glass: Color(0x8C161830),
    glassStrong: Color(0xC71A1C38),
    border: Color(0x1AFFFFFF),
    surface: Color(0xF01E2040),
    background: [Color(0xFF0F1024), Color(0xFF1A1236)],
    blobs: [Color(0xFF4338CA), Color(0xFF1D4ED8), Color(0xFF7E22CE)],
  );

  static GlassTokens of(BuildContext context) =>
      Theme.of(context).brightness == Brightness.dark ? dark : light;
}

/// Whether the glass is blurred (off in «حالت سبک»).
class GlassMode extends InheritedWidget {
  const GlassMode({super.key, required this.lite, required super.child});
  final bool lite;

  static bool liteOf(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<GlassMode>()?.lite ?? false;

  @override
  bool updateShouldNotify(GlassMode old) => old.lite != lite;
}

/// The soft gradient with coloured blobs behind every page.
class GlassBackground extends StatelessWidget {
  const GlassBackground({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final t = GlassTokens.of(context);
    final dark = Theme.of(context).brightness == Brightness.dark;
    Widget blob(Color c, double size, double alpha) => Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: RadialGradient(
          colors: [
            c.withValues(alpha: alpha),
            c.withValues(alpha: 0),
          ],
        ),
      ),
    );
    return DecoratedBox(
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topRight,
          end: Alignment.bottomLeft,
          colors: t.background,
        ),
      ),
      child: Stack(
        fit: StackFit.expand,
        children: [
          Positioned(
            top: -120,
            right: -110,
            child: blob(t.blobs[0], 380, dark ? .45 : .55),
          ),
          Positioned(
            bottom: 40,
            left: -120,
            child: blob(t.blobs[1], 340, dark ? .35 : .45),
          ),
          Positioned(
            top: 280,
            right: -140,
            child: blob(t.blobs[2], 260, dark ? .3 : .35),
          ),
          child,
        ],
      ),
    );
  }
}

/// Every pushed page gets the background (pages are opaque, so a transition never
/// shows two pages through each other); dialogs and sheets keep their own.
class GlassPageTransitions extends PageTransitionsBuilder {
  const GlassPageTransitions();

  static const _inner = FadeForwardsPageTransitionsBuilder();

  @override
  Widget buildTransitions<T>(
    PageRoute<T> route,
    BuildContext context,
    Animation<double> animation,
    Animation<double> secondaryAnimation,
    Widget child,
  ) => _inner.buildTransitions(
    route,
    context,
    animation,
    secondaryAnimation,
    GlassBackground(child: child),
  );
}

/// A frame of frosted glass. [strong] is the more opaque variant for sheets.
class GlassPanel extends StatelessWidget {
  const GlassPanel({
    super.key,
    required this.child,
    this.radius = const BorderRadius.all(Radius.circular(24)),
    this.padding = EdgeInsets.zero,
    this.strong = false,
  });

  final Widget child;
  final BorderRadius radius;
  final EdgeInsetsGeometry padding;
  final bool strong;

  @override
  Widget build(BuildContext context) {
    final t = GlassTokens.of(context);
    final lite = GlassMode.liteOf(context);
    final box = DecoratedBox(
      decoration: BoxDecoration(
        color: lite ? t.surface : (strong ? t.glassStrong : t.glass),
        borderRadius: radius,
        border: Border.all(color: t.border),
        boxShadow: [
          BoxShadow(
            color: const Color(0xFF3C328C).withValues(alpha: 0.16),
            blurRadius: 32,
            offset: const Offset(0, 8),
            spreadRadius: -8,
          ),
        ],
      ),
      // Tiles and ink inside the glass paint on this, not behind the tint.
      child: Material(
        type: MaterialType.transparency,
        child: Padding(padding: padding, child: child),
      ),
    );
    if (lite) return box;
    return ClipRRect(
      borderRadius: radius,
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 22, sigmaY: 22),
        child: box,
      ),
    );
  }
}

/// The main action: brand gradient, 52 high.
class BrandButton extends StatelessWidget {
  const BrandButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.busy = false,
  });

  final String label;
  final VoidCallback? onPressed;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    final enabled = onPressed != null && !busy;
    return Semantics(
      button: true,
      enabled: enabled,
      child: Opacity(
        opacity: enabled || busy ? 1 : .55,
        child: DecoratedBox(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            gradient: const LinearGradient(colors: [brand, brand2]),
            boxShadow: [
              BoxShadow(
                color: brand.withValues(alpha: 0.45),
                blurRadius: 24,
                offset: const Offset(0, 10),
                spreadRadius: -10,
              ),
            ],
          ),
          child: Material(
            type: MaterialType.transparency,
            child: InkWell(
              borderRadius: BorderRadius.circular(16),
              onTap: enabled ? onPressed : null,
              child: SizedBox(
                height: 52,
                child: Center(
                  child: busy
                      ? const SizedBox.square(
                          dimension: 22,
                          child: CircularProgressIndicator(
                            strokeWidth: 2.5,
                            color: Colors.white,
                          ),
                        )
                      : Text(
                          label,
                          style: const TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.w700,
                            fontSize: 16,
                          ),
                        ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// A short status: always text + icon (never colour alone).
class StatusPill extends StatelessWidget {
  const StatusPill({
    super.key,
    required this.icon,
    required this.label,
    required this.color,
  });

  final IconData icon;
  final String label;
  final Color color;

  static const ok = Color(0xFF047857);
  static const warning = Color(0xFFB45309);
  static const danger = Color(0xFFB91C1C);

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final c = dark ? Color.lerp(color, Colors.white, .45)! : color;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: dark ? 0.22 : 0.12),
        borderRadius: BorderRadius.circular(99),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 15, color: c),
          const SizedBox(width: 5),
          Flexible(
            child: Text(
              label,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: c,
                fontWeight: FontWeight.w700,
                fontSize: 12,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
