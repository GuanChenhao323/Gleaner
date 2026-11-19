import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'session.dart';

const _localeKey = 'app_locale';

const supportedAppLocales = <Locale>[
  Locale('en'),
  Locale('zh'),
  Locale('zh', 'TW'),
];

Locale parseAppLocale(String? raw) {
  switch (raw) {
    case 'zh':
    case 'zh_CN':
      return const Locale('zh');
    case 'zh_TW':
    case 'zh_HK':
      return const Locale('zh', 'TW');
    case 'en':
    default:
      return const Locale('en');
  }
}

String encodeAppLocale(Locale locale) {
  if (locale.languageCode == 'zh' && locale.countryCode == 'TW') return 'zh_TW';
  if (locale.languageCode == 'zh') return 'zh';
  return 'en';
}

class LocaleNotifier extends Notifier<Locale> {
  SharedPreferences get _prefs => ref.read(prefsProvider);

  @override
  Locale build() => parseAppLocale(_prefs.getString(_localeKey));

  Future<void> setLocale(Locale locale) async {
    final next = parseAppLocale(encodeAppLocale(locale));
    await _prefs.setString(_localeKey, encodeAppLocale(next));
    state = next;
  }
}

final localeProvider = NotifierProvider<LocaleNotifier, Locale>(LocaleNotifier.new);
