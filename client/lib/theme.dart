import 'package:flutter/material.dart';

class Brand {
  static const yellow = Color(0xFFE0A43A);
  static const ink = Color(0xFF121417);
  static const seed = ink;
  static const wheat = yellow;
  static const blue = ink;
  static const urgent = Color(0xFFD92D20);
  static const ok = Color(0xFF2E9D6A);

  static const dueCritical = Color(0xFFC9891F);
  static const dueSoon = yellow;
  static const dueOverdue = Color(0xFF9A7B4A);

  static const canvas = Color(0xFFF7F7F5);
  static const line = Color(0xFFE6E6E2);
  static const wash = Color(0xFFFFF6E8);

  /// 课程颜色：同一门课在列表、日历中保持同一颜色。
  static const coursePalette = [
    ink,
    Color(0xFF3D3A36),
    Color(0xFF6B645A),
    yellow,
    Color(0xFFC9891F),
    Color(0xFF5C6B5A),
    Color(0xFF8A6A3A),
    Color(0xFF4A5560),
  ];

  static Color course(String name) {
    if (name.isEmpty) return const Color(0xFF9A9080);
    var h = 0;
    for (final c in name.codeUnits) {
      h = (h * 31 + c) & 0x7fffffff;
    }
    return coursePalette[h % coursePalette.length];
  }

  static const labelPalette = <String>[
    '#E0A43A',
    '#D9534F',
    '#2E9D6A',
    '#3A7BD5',
    '#8B5CF6',
    '#E85D84',
    '#0F766E',
    '#5C4A2E',
  ];

  static Color labelColor(String hex, {Color fallback = yellow}) {
    if (hex.isEmpty) return fallback;
    final raw = hex.replaceFirst('#', '');
    if (raw.length != 6) return fallback;
    final v = int.tryParse(raw, radix: 16);
    if (v == null) return fallback;
    return Color(0xFF000000 | v);
  }
}

const _fallback = ['PingFang SC', 'Microsoft YaHei', 'Noto Sans SC', 'Noto Sans CJK SC', 'Source Han Sans SC', 'sans-serif'];
const _muted = Color(0xFF6B645A);

final _lightScheme = ColorScheme(
  brightness: Brightness.light,
  primary: Brand.ink,
  onPrimary: Colors.white,
  primaryContainer: Color(0xFFEEEEEA),
  onPrimaryContainer: Brand.ink,
  secondary: Brand.ink,
  onSecondary: Colors.white,
  secondaryContainer: Color(0xFFF0EFEA),
  onSecondaryContainer: Brand.ink,
  tertiary: Brand.yellow,
  onTertiary: Brand.ink,
  tertiaryContainer: Brand.wash,
  onTertiaryContainer: Brand.ink,
  error: Brand.urgent,
  onError: Colors.white,
  errorContainer: Color(0xFFFDECEC),
  onErrorContainer: Color(0xFF7A1A14),
  surface: Colors.white,
  onSurface: Brand.ink,
  onSurfaceVariant: _muted,
  outline: Color(0xFFD4D2CC),
  outlineVariant: Brand.line,
  shadow: Colors.black,
  scrim: Colors.black,
  inverseSurface: Brand.ink,
  onInverseSurface: Colors.white,
  inversePrimary: Brand.yellow,
  surfaceTint: Colors.transparent,
  surfaceContainerLowest: Colors.white,
  surfaceContainerLow: Colors.white,
  surfaceContainer: Brand.canvas,
  surfaceContainerHigh: Color(0xFFEEEEEA),
  surfaceContainerHighest: Color(0xFFE6E6E2),
);

final _darkScheme = ColorScheme.fromSeed(seedColor: Brand.ink, brightness: Brightness.dark);

ThemeData buildTheme(Brightness b) {
  final scheme = b == Brightness.light ? _lightScheme : _darkScheme;
  final base = ThemeData(colorScheme: scheme, useMaterial3: true, brightness: b);
  final text = base.textTheme.apply(fontFamilyFallback: _fallback);
  return base.copyWith(
    textTheme: text.copyWith(
      headlineMedium: text.headlineMedium?.copyWith(fontWeight: FontWeight.w700, letterSpacing: -0.5),
      titleLarge: text.titleLarge?.copyWith(fontWeight: FontWeight.w700),
      titleMedium: text.titleMedium?.copyWith(fontWeight: FontWeight.w600),
    ),
    scaffoldBackgroundColor: b == Brightness.light ? Brand.canvas : scheme.surface,
    appBarTheme: AppBarTheme(
      backgroundColor: scheme.surface,
      surfaceTintColor: Colors.transparent,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: text.titleLarge?.copyWith(color: scheme.onSurface, fontWeight: FontWeight.w700),
    ),
    cardTheme: CardThemeData(
      elevation: 0,
      color: scheme.surface,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: scheme.outlineVariant),
      ),
      clipBehavior: Clip.antiAlias,
    ),
    chipTheme: ChipThemeData(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      side: BorderSide(color: scheme.outlineVariant),
      labelStyle: text.labelMedium,
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: scheme.surfaceContainerHighest.withValues(alpha: 0.5),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide.none),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: scheme.surface,
      indicatorColor: scheme.secondaryContainer,
      labelTextStyle: WidgetStatePropertyAll(text.labelSmall?.copyWith(fontWeight: FontWeight.w600)),
      height: 68,
    ),
    navigationRailTheme: NavigationRailThemeData(
      backgroundColor: scheme.surface,
      indicatorColor: scheme.secondaryContainer,
      labelType: NavigationRailLabelType.none,
    ),
    listTileTheme: ListTileThemeData(shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14))),
    dividerTheme: DividerThemeData(color: scheme.outlineVariant.withValues(alpha: 0.5), space: 1),
    snackBarTheme: SnackBarThemeData(behavior: SnackBarBehavior.floating, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12))),
    bottomSheetTheme: const BottomSheetThemeData(showDragHandle: true, shape: RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(28)))),
    dialogTheme: DialogThemeData(shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24))),
  );
}
