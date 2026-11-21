import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'app_localizations_en.dart';
import 'app_localizations_zh.dart';

// ignore_for_file: type=lint

/// Callers can lookup localized strings with an instance of AppLocalizations
/// returned by `AppLocalizations.of(context)`.
///
/// Applications need to include `AppLocalizations.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'l10n/app_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: AppLocalizations.localizationsDelegates,
///   supportedLocales: AppLocalizations.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the AppLocalizations.supportedLocales
/// property.
abstract class AppLocalizations {
  AppLocalizations(String locale)
    : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static AppLocalizations of(BuildContext context) {
    return Localizations.of<AppLocalizations>(context, AppLocalizations)!;
  }

  static const LocalizationsDelegate<AppLocalizations> delegate =
      _AppLocalizationsDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates =
      <LocalizationsDelegate<dynamic>>[
        delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
      ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[
    Locale('en'),
    Locale('zh'),
    Locale('zh', 'TW'),
  ];

  /// No description provided for @appTitle.
  ///
  /// In en, this message translates to:
  /// **'Gleaner'**
  String get appTitle;

  /// No description provided for @navDesk.
  ///
  /// In en, this message translates to:
  /// **'Desk'**
  String get navDesk;

  /// No description provided for @navInbox.
  ///
  /// In en, this message translates to:
  /// **'Inbox'**
  String get navInbox;

  /// No description provided for @navCourses.
  ///
  /// In en, this message translates to:
  /// **'Courses'**
  String get navCourses;

  /// No description provided for @navSources.
  ///
  /// In en, this message translates to:
  /// **'Sources'**
  String get navSources;

  /// No description provided for @navSettings.
  ///
  /// In en, this message translates to:
  /// **'Settings'**
  String get navSettings;

  /// No description provided for @navCompose.
  ///
  /// In en, this message translates to:
  /// **'Compose'**
  String get navCompose;

  /// No description provided for @navTransfer.
  ///
  /// In en, this message translates to:
  /// **'Transfer'**
  String get navTransfer;

  /// No description provided for @navAccount.
  ///
  /// In en, this message translates to:
  /// **'Account'**
  String get navAccount;

  /// No description provided for @navMore.
  ///
  /// In en, this message translates to:
  /// **'More'**
  String get navMore;

  /// No description provided for @actionView.
  ///
  /// In en, this message translates to:
  /// **'View'**
  String get actionView;

  /// No description provided for @actionClose.
  ///
  /// In en, this message translates to:
  /// **'Close'**
  String get actionClose;

  /// No description provided for @actionSave.
  ///
  /// In en, this message translates to:
  /// **'Save'**
  String get actionSave;

  /// No description provided for @actionCancel.
  ///
  /// In en, this message translates to:
  /// **'Cancel'**
  String get actionCancel;

  /// No description provided for @actionGotIt.
  ///
  /// In en, this message translates to:
  /// **'Got it'**
  String get actionGotIt;

  /// No description provided for @actionSyncNow.
  ///
  /// In en, this message translates to:
  /// **'Sync now'**
  String get actionSyncNow;

  /// No description provided for @login.
  ///
  /// In en, this message translates to:
  /// **'Sign in'**
  String get login;

  /// No description provided for @loginOrRegister.
  ///
  /// In en, this message translates to:
  /// **'Sign in or register'**
  String get loginOrRegister;

  /// No description provided for @register.
  ///
  /// In en, this message translates to:
  /// **'Create account'**
  String get register;

  /// No description provided for @registerAndStart.
  ///
  /// In en, this message translates to:
  /// **'Register and start'**
  String get registerAndStart;

  /// No description provided for @email.
  ///
  /// In en, this message translates to:
  /// **'Email'**
  String get email;

  /// No description provided for @password.
  ///
  /// In en, this message translates to:
  /// **'Password'**
  String get password;

  /// No description provided for @passwordMin8.
  ///
  /// In en, this message translates to:
  /// **'Password (at least 8 characters)'**
  String get passwordMin8;

  /// No description provided for @emailCode.
  ///
  /// In en, this message translates to:
  /// **'Email code'**
  String get emailCode;

  /// No description provided for @getCode.
  ///
  /// In en, this message translates to:
  /// **'Get code'**
  String get getCode;

  /// No description provided for @resendInSeconds.
  ///
  /// In en, this message translates to:
  /// **'{seconds}s to resend'**
  String resendInSeconds(int seconds);

  /// No description provided for @nickname.
  ///
  /// In en, this message translates to:
  /// **'Display name'**
  String get nickname;

  /// No description provided for @grade.
  ///
  /// In en, this message translates to:
  /// **'Year'**
  String get grade;

  /// No description provided for @major.
  ///
  /// In en, this message translates to:
  /// **'Major'**
  String get major;

  /// No description provided for @agreePrivacy.
  ///
  /// In en, this message translates to:
  /// **'I have read the privacy notice'**
  String get agreePrivacy;

  /// No description provided for @privacyAgreeDetail.
  ///
  /// In en, this message translates to:
  /// **'Gleaner stores Moodle session cookies, not SSO passwords. School mailbox app passwords are encrypted with AES-GCM. Mail keeps only subject, sender, summary, and links. You can delete your account anytime.'**
  String get privacyAgreeDetail;

  /// No description provided for @serverAddress.
  ///
  /// In en, this message translates to:
  /// **'Server URL'**
  String get serverAddress;

  /// No description provided for @haveAccountSignIn.
  ///
  /// In en, this message translates to:
  /// **'Already have an account? Sign in'**
  String get haveAccountSignIn;

  /// No description provided for @noAccountRegister.
  ///
  /// In en, this message translates to:
  /// **'No account yet? Register'**
  String get noAccountRegister;

  /// No description provided for @codeSent.
  ///
  /// In en, this message translates to:
  /// **'Code sent to {email}. Valid for 10 minutes.'**
  String codeSent(String email);

  /// No description provided for @guestDesk.
  ///
  /// In en, this message translates to:
  /// **'Sign in to see today’s tasks and deadlines this week.'**
  String get guestDesk;

  /// No description provided for @guestInbox.
  ///
  /// In en, this message translates to:
  /// **'Sign in to see assignments, notices, and page updates.'**
  String get guestInbox;

  /// No description provided for @guestCourses.
  ///
  /// In en, this message translates to:
  /// **'Sign in to browse assignments and deadlines by course.'**
  String get guestCourses;

  /// No description provided for @guestSources.
  ///
  /// In en, this message translates to:
  /// **'Sign in to manage campus pages and Moodle sources.'**
  String get guestSources;

  /// No description provided for @guestSettings.
  ///
  /// In en, this message translates to:
  /// **'Sign in to manage your profile and notification settings.'**
  String get guestSettings;

  /// No description provided for @sectionNotifications.
  ///
  /// In en, this message translates to:
  /// **'Notifications'**
  String get sectionNotifications;

  /// No description provided for @sectionConnection.
  ///
  /// In en, this message translates to:
  /// **'Connection'**
  String get sectionConnection;

  /// No description provided for @sectionAccount.
  ///
  /// In en, this message translates to:
  /// **'Account'**
  String get sectionAccount;

  /// No description provided for @quietHours.
  ///
  /// In en, this message translates to:
  /// **'Do not disturb'**
  String get quietHours;

  /// No description provided for @dailyDigest.
  ///
  /// In en, this message translates to:
  /// **'Daily digest'**
  String get dailyDigest;

  /// No description provided for @dailyDigestAt.
  ///
  /// In en, this message translates to:
  /// **'Every day at {time}'**
  String dailyDigestAt(String time);

  /// No description provided for @digestAlsoEmail.
  ///
  /// In en, this message translates to:
  /// **'Also email the digest'**
  String get digestAlsoEmail;

  /// No description provided for @personalRules.
  ///
  /// In en, this message translates to:
  /// **'Personal rules'**
  String get personalRules;

  /// No description provided for @pushStatus.
  ///
  /// In en, this message translates to:
  /// **'Push status'**
  String get pushStatus;

  /// No description provided for @connected.
  ///
  /// In en, this message translates to:
  /// **'Connected'**
  String get connected;

  /// No description provided for @connecting.
  ///
  /// In en, this message translates to:
  /// **'Connecting…'**
  String get connecting;

  /// No description provided for @disconnected.
  ///
  /// In en, this message translates to:
  /// **'Disconnected'**
  String get disconnected;

  /// No description provided for @sync.
  ///
  /// In en, this message translates to:
  /// **'Sync'**
  String get sync;

  /// No description provided for @syncPending.
  ///
  /// In en, this message translates to:
  /// **'{count} pending'**
  String syncPending(int count);

  /// No description provided for @syncUpToDate.
  ///
  /// In en, this message translates to:
  /// **'Up to date'**
  String get syncUpToDate;

  /// No description provided for @server.
  ///
  /// In en, this message translates to:
  /// **'Server'**
  String get server;

  /// No description provided for @privacy.
  ///
  /// In en, this message translates to:
  /// **'Privacy'**
  String get privacy;

  /// No description provided for @privacyBody.
  ///
  /// In en, this message translates to:
  /// **'Moodle and similar sources keep login sessions only, not SSO passwords. School mailbox app passwords and sessions are encrypted with AES-GCM. Mail keeps only subject, sender, summary, and links. You can delete your account and all data anytime.'**
  String get privacyBody;

  /// No description provided for @changePassword.
  ///
  /// In en, this message translates to:
  /// **'Change password'**
  String get changePassword;

  /// No description provided for @signOut.
  ///
  /// In en, this message translates to:
  /// **'Sign out'**
  String get signOut;

  /// No description provided for @deleteAccount.
  ///
  /// In en, this message translates to:
  /// **'Delete account'**
  String get deleteAccount;

  /// No description provided for @language.
  ///
  /// In en, this message translates to:
  /// **'Language'**
  String get language;

  /// No description provided for @languageEnglish.
  ///
  /// In en, this message translates to:
  /// **'English'**
  String get languageEnglish;

  /// No description provided for @languageSimplified.
  ///
  /// In en, this message translates to:
  /// **'简体中文'**
  String get languageSimplified;

  /// No description provided for @languageTraditional.
  ///
  /// In en, this message translates to:
  /// **'繁體中文'**
  String get languageTraditional;

  /// No description provided for @inboxUnread.
  ///
  /// In en, this message translates to:
  /// **'Unread'**
  String get inboxUnread;

  /// No description provided for @inboxStarred.
  ///
  /// In en, this message translates to:
  /// **'Starred'**
  String get inboxStarred;

  /// No description provided for @inboxTodo.
  ///
  /// In en, this message translates to:
  /// **'To-do'**
  String get inboxTodo;

  /// No description provided for @inboxEvent.
  ///
  /// In en, this message translates to:
  /// **'Events'**
  String get inboxEvent;

  /// No description provided for @inboxNotice.
  ///
  /// In en, this message translates to:
  /// **'Notices'**
  String get inboxNotice;

  /// No description provided for @inboxTrash.
  ///
  /// In en, this message translates to:
  /// **'Trash'**
  String get inboxTrash;

  /// No description provided for @statusOpen.
  ///
  /// In en, this message translates to:
  /// **'Open'**
  String get statusOpen;

  /// No description provided for @statusDone.
  ///
  /// In en, this message translates to:
  /// **'Done'**
  String get statusDone;

  /// No description provided for @statusActive.
  ///
  /// In en, this message translates to:
  /// **'Active'**
  String get statusActive;

  /// No description provided for @statusArchived.
  ///
  /// In en, this message translates to:
  /// **'Archived'**
  String get statusArchived;

  /// No description provided for @statusUnread.
  ///
  /// In en, this message translates to:
  /// **'Unread'**
  String get statusUnread;

  /// No description provided for @statusRead.
  ///
  /// In en, this message translates to:
  /// **'Read'**
  String get statusRead;

  /// No description provided for @statusAll.
  ///
  /// In en, this message translates to:
  /// **'All'**
  String get statusAll;

  /// No description provided for @newLabel.
  ///
  /// In en, this message translates to:
  /// **'New label'**
  String get newLabel;

  /// No description provided for @labels.
  ///
  /// In en, this message translates to:
  /// **'Labels'**
  String get labels;

  /// No description provided for @pinSidebar.
  ///
  /// In en, this message translates to:
  /// **'Pin sidebar'**
  String get pinSidebar;

  /// No description provided for @unpinSidebar.
  ///
  /// In en, this message translates to:
  /// **'Unpin sidebar'**
  String get unpinSidebar;

  /// No description provided for @saved.
  ///
  /// In en, this message translates to:
  /// **'Saved'**
  String get saved;

  /// No description provided for @classmate.
  ///
  /// In en, this message translates to:
  /// **'there'**
  String get classmate;

  /// No description provided for @justNow.
  ///
  /// In en, this message translates to:
  /// **'Just now'**
  String get justNow;

  /// No description provided for @never.
  ///
  /// In en, this message translates to:
  /// **'Never'**
  String get never;

  /// No description provided for @minutesAgo.
  ///
  /// In en, this message translates to:
  /// **'{count} min ago'**
  String minutesAgo(int count);

  /// No description provided for @hoursAgo.
  ///
  /// In en, this message translates to:
  /// **'{count} h ago'**
  String hoursAgo(int count);

  /// No description provided for @yesterdayAt.
  ///
  /// In en, this message translates to:
  /// **'Yesterday {time}'**
  String yesterdayAt(String time);

  /// No description provided for @today.
  ///
  /// In en, this message translates to:
  /// **'Today'**
  String get today;

  /// No description provided for @tomorrow.
  ///
  /// In en, this message translates to:
  /// **'Tomorrow'**
  String get tomorrow;

  /// No description provided for @dayAfterTomorrow.
  ///
  /// In en, this message translates to:
  /// **'In 2 days'**
  String get dayAfterTomorrow;

  /// No description provided for @yesterday.
  ///
  /// In en, this message translates to:
  /// **'Yesterday'**
  String get yesterday;

  /// No description provided for @overdueHours.
  ///
  /// In en, this message translates to:
  /// **'Overdue {count} h'**
  String overdueHours(int count);

  /// No description provided for @overdueDays.
  ///
  /// In en, this message translates to:
  /// **'Overdue {count} d'**
  String overdueDays(int count);

  /// No description provided for @remainingMinutes.
  ///
  /// In en, this message translates to:
  /// **'{count} min left'**
  String remainingMinutes(int count);

  /// No description provided for @remainingHours.
  ///
  /// In en, this message translates to:
  /// **'{count} h left'**
  String remainingHours(int count);

  /// No description provided for @remainingDaysHours.
  ///
  /// In en, this message translates to:
  /// **'{days} d {hours} h left'**
  String remainingDaysHours(int days, int hours);

  /// No description provided for @remainingDays.
  ///
  /// In en, this message translates to:
  /// **'{count} d left'**
  String remainingDays(int count);

  /// No description provided for @kindAssignment.
  ///
  /// In en, this message translates to:
  /// **'Assignment'**
  String get kindAssignment;

  /// No description provided for @kindEvent.
  ///
  /// In en, this message translates to:
  /// **'Event'**
  String get kindEvent;

  /// No description provided for @kindNotice.
  ///
  /// In en, this message translates to:
  /// **'Notice'**
  String get kindNotice;

  /// No description provided for @kindMail.
  ///
  /// In en, this message translates to:
  /// **'Mail'**
  String get kindMail;

  /// No description provided for @kindClip.
  ///
  /// In en, this message translates to:
  /// **'Clip'**
  String get kindClip;

  /// No description provided for @kindPage.
  ///
  /// In en, this message translates to:
  /// **'Page'**
  String get kindPage;

  /// No description provided for @kindItem.
  ///
  /// In en, this message translates to:
  /// **'Item'**
  String get kindItem;

  /// No description provided for @channelWeb.
  ///
  /// In en, this message translates to:
  /// **'Website'**
  String get channelWeb;

  /// No description provided for @channelMail.
  ///
  /// In en, this message translates to:
  /// **'Mail'**
  String get channelMail;

  /// No description provided for @sourceOk.
  ///
  /// In en, this message translates to:
  /// **'OK'**
  String get sourceOk;

  /// No description provided for @sourceFailed.
  ///
  /// In en, this message translates to:
  /// **'Check failed'**
  String get sourceFailed;

  /// No description provided for @sourceNeedLogin.
  ///
  /// In en, this message translates to:
  /// **'Sign in again'**
  String get sourceNeedLogin;

  /// No description provided for @sourceWaiting.
  ///
  /// In en, this message translates to:
  /// **'Waiting for first check'**
  String get sourceWaiting;

  /// No description provided for @greetingLateNight.
  ///
  /// In en, this message translates to:
  /// **'Still up'**
  String get greetingLateNight;

  /// No description provided for @greetingMorning.
  ///
  /// In en, this message translates to:
  /// **'Good morning'**
  String get greetingMorning;

  /// No description provided for @greetingNoon.
  ///
  /// In en, this message translates to:
  /// **'Good noon'**
  String get greetingNoon;

  /// No description provided for @greetingAfternoon.
  ///
  /// In en, this message translates to:
  /// **'Good afternoon'**
  String get greetingAfternoon;

  /// No description provided for @greetingEvening.
  ///
  /// In en, this message translates to:
  /// **'Good evening'**
  String get greetingEvening;

  /// No description provided for @priorityUrgent.
  ///
  /// In en, this message translates to:
  /// **'Urgent'**
  String get priorityUrgent;

  /// No description provided for @priorityNormal.
  ///
  /// In en, this message translates to:
  /// **'Normal'**
  String get priorityNormal;

  /// No description provided for @priorityLow.
  ///
  /// In en, this message translates to:
  /// **'Low'**
  String get priorityLow;

  /// No description provided for @typeTodo.
  ///
  /// In en, this message translates to:
  /// **'To-do'**
  String get typeTodo;

  /// No description provided for @typeEvent.
  ///
  /// In en, this message translates to:
  /// **'Event'**
  String get typeEvent;

  /// No description provided for @typeNotice.
  ///
  /// In en, this message translates to:
  /// **'Notice'**
  String get typeNotice;

  /// No description provided for @typeReference.
  ///
  /// In en, this message translates to:
  /// **'Reference'**
  String get typeReference;

  /// No description provided for @markOpen.
  ///
  /// In en, this message translates to:
  /// **'Mark open'**
  String get markOpen;

  /// No description provided for @markDone.
  ///
  /// In en, this message translates to:
  /// **'Mark done'**
  String get markDone;

  /// No description provided for @unarchive.
  ///
  /// In en, this message translates to:
  /// **'Unarchive'**
  String get unarchive;

  /// No description provided for @archive.
  ///
  /// In en, this message translates to:
  /// **'Archive'**
  String get archive;

  /// No description provided for @markUnread.
  ///
  /// In en, this message translates to:
  /// **'Mark unread'**
  String get markUnread;

  /// No description provided for @markRead.
  ///
  /// In en, this message translates to:
  /// **'Mark read'**
  String get markRead;

  /// No description provided for @fieldTitle.
  ///
  /// In en, this message translates to:
  /// **'Title'**
  String get fieldTitle;

  /// No description provided for @fieldSummary.
  ///
  /// In en, this message translates to:
  /// **'Summary'**
  String get fieldSummary;

  /// No description provided for @fieldType.
  ///
  /// In en, this message translates to:
  /// **'Type'**
  String get fieldType;

  /// No description provided for @fieldDeadline.
  ///
  /// In en, this message translates to:
  /// **'Deadline'**
  String get fieldDeadline;

  /// No description provided for @fieldStart.
  ///
  /// In en, this message translates to:
  /// **'Start'**
  String get fieldStart;

  /// No description provided for @fieldEnd.
  ///
  /// In en, this message translates to:
  /// **'End'**
  String get fieldEnd;

  /// No description provided for @fieldLocation.
  ///
  /// In en, this message translates to:
  /// **'Location'**
  String get fieldLocation;

  /// No description provided for @fieldRequirements.
  ///
  /// In en, this message translates to:
  /// **'Requirements'**
  String get fieldRequirements;

  /// No description provided for @emptyValue.
  ///
  /// In en, this message translates to:
  /// **'(empty)'**
  String get emptyValue;

  /// No description provided for @done.
  ///
  /// In en, this message translates to:
  /// **'Done'**
  String get done;

  /// No description provided for @deskTodayFocus.
  ///
  /// In en, this message translates to:
  /// **'Today'**
  String get deskTodayFocus;

  /// No description provided for @deskThisWeek.
  ///
  /// In en, this message translates to:
  /// **'This week'**
  String get deskThisWeek;

  /// No description provided for @deskNeedsAttention.
  ///
  /// In en, this message translates to:
  /// **'Needs attention'**
  String get deskNeedsAttention;

  /// No description provided for @deskCalendar.
  ///
  /// In en, this message translates to:
  /// **'Calendar'**
  String get deskCalendar;

  /// No description provided for @deskHideCalendar.
  ///
  /// In en, this message translates to:
  /// **'Hide calendar'**
  String get deskHideCalendar;

  /// No description provided for @deskDueIn7Days.
  ///
  /// In en, this message translates to:
  /// **'Due in 7 days'**
  String get deskDueIn7Days;

  /// No description provided for @deskSourceIssues.
  ///
  /// In en, this message translates to:
  /// **'Source issues'**
  String get deskSourceIssues;

  /// No description provided for @deskShowMore.
  ///
  /// In en, this message translates to:
  /// **'Show more'**
  String get deskShowMore;

  /// No description provided for @deskInboxLink.
  ///
  /// In en, this message translates to:
  /// **'Inbox'**
  String get deskInboxLink;

  /// No description provided for @filterAll.
  ///
  /// In en, this message translates to:
  /// **'All'**
  String get filterAll;

  /// No description provided for @summary.
  ///
  /// In en, this message translates to:
  /// **'Summary'**
  String get summary;

  /// No description provided for @requirements.
  ///
  /// In en, this message translates to:
  /// **'Requirements'**
  String get requirements;

  /// No description provided for @originalContent.
  ///
  /// In en, this message translates to:
  /// **'Original'**
  String get originalContent;

  /// No description provided for @sourceMonitor.
  ///
  /// In en, this message translates to:
  /// **'Source monitoring'**
  String get sourceMonitor;

  /// No description provided for @deadlineAt.
  ///
  /// In en, this message translates to:
  /// **'Due {when}'**
  String deadlineAt(String when);

  /// No description provided for @openSource.
  ///
  /// In en, this message translates to:
  /// **'Open source'**
  String get openSource;

  /// No description provided for @edit.
  ///
  /// In en, this message translates to:
  /// **'Edit'**
  String get edit;

  /// No description provided for @notImportant.
  ///
  /// In en, this message translates to:
  /// **'Not important'**
  String get notImportant;

  /// No description provided for @copyLink.
  ///
  /// In en, this message translates to:
  /// **'Copy link'**
  String get copyLink;

  /// No description provided for @star.
  ///
  /// In en, this message translates to:
  /// **'Star'**
  String get star;

  /// No description provided for @unstar.
  ///
  /// In en, this message translates to:
  /// **'Unstar'**
  String get unstar;

  /// No description provided for @weekdayMon.
  ///
  /// In en, this message translates to:
  /// **'Mon'**
  String get weekdayMon;

  /// No description provided for @weekdayTue.
  ///
  /// In en, this message translates to:
  /// **'Tue'**
  String get weekdayTue;

  /// No description provided for @weekdayWed.
  ///
  /// In en, this message translates to:
  /// **'Wed'**
  String get weekdayWed;

  /// No description provided for @weekdayThu.
  ///
  /// In en, this message translates to:
  /// **'Thu'**
  String get weekdayThu;

  /// No description provided for @weekdayFri.
  ///
  /// In en, this message translates to:
  /// **'Fri'**
  String get weekdayFri;

  /// No description provided for @weekdaySat.
  ///
  /// In en, this message translates to:
  /// **'Sat'**
  String get weekdaySat;

  /// No description provided for @weekdaySun.
  ///
  /// In en, this message translates to:
  /// **'Sun'**
  String get weekdaySun;

  /// No description provided for @generateQr.
  ///
  /// In en, this message translates to:
  /// **'Generate QR code'**
  String get generateQr;

  /// No description provided for @orEnterCode.
  ///
  /// In en, this message translates to:
  /// **'Or enter pairing code'**
  String get orEnterCode;

  /// No description provided for @codeHint.
  ///
  /// In en, this message translates to:
  /// **'6-digit code'**
  String get codeHint;

  /// No description provided for @join.
  ///
  /// In en, this message translates to:
  /// **'Join'**
  String get join;

  /// No description provided for @scanQr.
  ///
  /// In en, this message translates to:
  /// **'Scan QR code'**
  String get scanQr;

  /// No description provided for @codeValid30m.
  ///
  /// In en, this message translates to:
  /// **'Code valid for 30 minutes'**
  String get codeValid30m;

  /// No description provided for @paired.
  ///
  /// In en, this message translates to:
  /// **'Paired'**
  String get paired;

  /// No description provided for @waitingPair.
  ///
  /// In en, this message translates to:
  /// **'Waiting to pair…'**
  String get waitingPair;

  /// No description provided for @sendFile.
  ///
  /// In en, this message translates to:
  /// **'Send file'**
  String get sendFile;

  /// No description provided for @files.
  ///
  /// In en, this message translates to:
  /// **'Files'**
  String get files;

  /// No description provided for @noFilesYet.
  ///
  /// In en, this message translates to:
  /// **'No files yet'**
  String get noFilesYet;

  /// No description provided for @send.
  ///
  /// In en, this message translates to:
  /// **'Send'**
  String get send;

  /// No description provided for @to.
  ///
  /// In en, this message translates to:
  /// **'To'**
  String get to;

  /// No description provided for @ccOptional.
  ///
  /// In en, this message translates to:
  /// **'Cc (optional)'**
  String get ccOptional;

  /// No description provided for @subject.
  ///
  /// In en, this message translates to:
  /// **'Subject'**
  String get subject;

  /// No description provided for @bodyHint.
  ///
  /// In en, this message translates to:
  /// **'Message'**
  String get bodyHint;

  /// No description provided for @addAttachment.
  ///
  /// In en, this message translates to:
  /// **'Attach'**
  String get addAttachment;

  /// No description provided for @recentSent.
  ///
  /// In en, this message translates to:
  /// **'Recently sent'**
  String get recentSent;

  /// No description provided for @noSubject.
  ///
  /// In en, this message translates to:
  /// **'(no subject)'**
  String get noSubject;

  /// No description provided for @pleaseFillRecipient.
  ///
  /// In en, this message translates to:
  /// **'Enter a recipient'**
  String get pleaseFillRecipient;

  /// No description provided for @sent.
  ///
  /// In en, this message translates to:
  /// **'Sent'**
  String get sent;

  /// No description provided for @duplicateSend.
  ///
  /// In en, this message translates to:
  /// **'Already sent; not sent again'**
  String get duplicateSend;

  /// No description provided for @sendFailed.
  ///
  /// In en, this message translates to:
  /// **'Send failed: {error}'**
  String sendFailed(String error);

  /// No description provided for @lastCheckFailed.
  ///
  /// In en, this message translates to:
  /// **'Last check failed'**
  String get lastCheckFailed;

  /// No description provided for @lastSuccessCheck.
  ///
  /// In en, this message translates to:
  /// **'Last successful check'**
  String get lastSuccessCheck;

  /// No description provided for @reason.
  ///
  /// In en, this message translates to:
  /// **'Reason'**
  String get reason;

  /// No description provided for @failedAt.
  ///
  /// In en, this message translates to:
  /// **'Failed'**
  String get failedAt;

  /// No description provided for @nextCheck.
  ///
  /// In en, this message translates to:
  /// **'Next check'**
  String get nextCheck;

  /// No description provided for @goHandle.
  ///
  /// In en, this message translates to:
  /// **'Fix'**
  String get goHandle;

  /// No description provided for @fieldBody.
  ///
  /// In en, this message translates to:
  /// **'Body'**
  String get fieldBody;

  /// No description provided for @operationFailed.
  ///
  /// In en, this message translates to:
  /// **'Failed: {error}'**
  String operationFailed(String error);

  /// No description provided for @pluginCapture.
  ///
  /// In en, this message translates to:
  /// **'Extension capture'**
  String get pluginCapture;

  /// No description provided for @alreadyStarted.
  ///
  /// In en, this message translates to:
  /// **'Started'**
  String get alreadyStarted;

  /// No description provided for @conflictBanner.
  ///
  /// In en, this message translates to:
  /// **'Source content you edited also changed. Choose which version to keep.'**
  String get conflictBanner;

  /// No description provided for @mineValue.
  ///
  /// In en, this message translates to:
  /// **'Mine: {value}'**
  String mineValue(String value);

  /// No description provided for @sourceValue.
  ///
  /// In en, this message translates to:
  /// **'Source: {value}'**
  String sourceValue(String value);

  /// No description provided for @keepMine.
  ///
  /// In en, this message translates to:
  /// **'Keep mine'**
  String get keepMine;

  /// No description provided for @useSource.
  ///
  /// In en, this message translates to:
  /// **'Use source'**
  String get useSource;

  /// No description provided for @monitorUnsupported.
  ///
  /// In en, this message translates to:
  /// **'Auto-check not supported; open the source to verify manually'**
  String get monitorUnsupported;

  /// No description provided for @monitorDisabled.
  ///
  /// In en, this message translates to:
  /// **'Auto-check is off'**
  String get monitorDisabled;

  /// No description provided for @monitorPending.
  ///
  /// In en, this message translates to:
  /// **'On; waiting for first check'**
  String get monitorPending;

  /// No description provided for @monitorUnchanged.
  ///
  /// In en, this message translates to:
  /// **'Last check: no change'**
  String get monitorUnchanged;

  /// No description provided for @monitorChanged.
  ///
  /// In en, this message translates to:
  /// **'Last check: changes found'**
  String get monitorChanged;

  /// No description provided for @monitorFailed.
  ///
  /// In en, this message translates to:
  /// **'Last check failed'**
  String get monitorFailed;

  /// No description provided for @errAuthExpired.
  ///
  /// In en, this message translates to:
  /// **'Login expired: sign in again in the browser'**
  String get errAuthExpired;

  /// No description provided for @errForbidden.
  ///
  /// In en, this message translates to:
  /// **'No permission to open this page'**
  String get errForbidden;

  /// No description provided for @errNetwork.
  ///
  /// In en, this message translates to:
  /// **'Network error'**
  String get errNetwork;

  /// No description provided for @errNotFound.
  ///
  /// In en, this message translates to:
  /// **'Item not found on the page'**
  String get errNotFound;

  /// No description provided for @errParseFailed.
  ///
  /// In en, this message translates to:
  /// **'Page structure changed; cannot parse yet'**
  String get errParseFailed;

  /// No description provided for @errUnsupported.
  ///
  /// In en, this message translates to:
  /// **'This page no longer supports auto-check'**
  String get errUnsupported;

  /// No description provided for @lastSuccessNever.
  ///
  /// In en, this message translates to:
  /// **'none yet'**
  String get lastSuccessNever;

  /// No description provided for @lastSuccessCheckLine.
  ///
  /// In en, this message translates to:
  /// **'Last successful check: {when}'**
  String lastSuccessCheckLine(String when);

  /// No description provided for @reasonLine.
  ///
  /// In en, this message translates to:
  /// **'Reason: {reason}'**
  String reasonLine(String reason);

  /// No description provided for @failedAtLine.
  ///
  /// In en, this message translates to:
  /// **'Failed: {when}'**
  String failedAtLine(String when);

  /// No description provided for @nextCheckLine.
  ///
  /// In en, this message translates to:
  /// **'Next check: {when} (needs Chrome and local backend)'**
  String nextCheckLine(String when);

  /// No description provided for @restoreSourceValue.
  ///
  /// In en, this message translates to:
  /// **'Restore source'**
  String get restoreSourceValue;

  /// No description provided for @willRestoreSource.
  ///
  /// In en, this message translates to:
  /// **'Will restore source'**
  String get willRestoreSource;

  /// No description provided for @notSet.
  ///
  /// In en, this message translates to:
  /// **'Not set'**
  String get notSet;

  /// No description provided for @choose.
  ///
  /// In en, this message translates to:
  /// **'Choose'**
  String get choose;

  /// No description provided for @clear.
  ///
  /// In en, this message translates to:
  /// **'Clear'**
  String get clear;

  /// No description provided for @editItem.
  ///
  /// In en, this message translates to:
  /// **'Edit item'**
  String get editItem;

  /// No description provided for @editItemHint.
  ///
  /// In en, this message translates to:
  /// **'Edits only affect what you see. Source updates won’t overwrite them; you’ll be asked if the source also changes.'**
  String get editItemHint;

  /// No description provided for @editsSaved.
  ///
  /// In en, this message translates to:
  /// **'Changes saved'**
  String get editsSaved;

  /// No description provided for @oldValue.
  ///
  /// In en, this message translates to:
  /// **'Old: {value}'**
  String oldValue(String value);

  /// No description provided for @newValue.
  ///
  /// In en, this message translates to:
  /// **'New: {value}'**
  String newValue(String value);

  /// No description provided for @filterTodoTasks.
  ///
  /// In en, this message translates to:
  /// **'To-dos'**
  String get filterTodoTasks;

  /// No description provided for @filterEvents.
  ///
  /// In en, this message translates to:
  /// **'Events'**
  String get filterEvents;

  /// No description provided for @filterNotices.
  ///
  /// In en, this message translates to:
  /// **'Notices'**
  String get filterNotices;

  /// No description provided for @todayShort.
  ///
  /// In en, this message translates to:
  /// **'Today'**
  String get todayShort;

  /// No description provided for @monthDay.
  ///
  /// In en, this message translates to:
  /// **'{month}/{day}'**
  String monthDay(int month, int day);

  /// No description provided for @scorePoints.
  ///
  /// In en, this message translates to:
  /// **'{score} pts'**
  String scorePoints(num score);

  /// No description provided for @webMaterial.
  ///
  /// In en, this message translates to:
  /// **'Web clip'**
  String get webMaterial;

  /// No description provided for @sourceDeleted.
  ///
  /// In en, this message translates to:
  /// **'Removed at source'**
  String get sourceDeleted;

  /// No description provided for @originalTitle.
  ///
  /// In en, this message translates to:
  /// **'Original title: {title}'**
  String originalTitle(String title);

  /// No description provided for @sourceAndReliability.
  ///
  /// In en, this message translates to:
  /// **'Source & reliability'**
  String get sourceAndReliability;

  /// No description provided for @unknownSource.
  ///
  /// In en, this message translates to:
  /// **'Unknown source'**
  String get unknownSource;

  /// No description provided for @lastSaved.
  ///
  /// In en, this message translates to:
  /// **'Last saved'**
  String get lastSaved;

  /// No description provided for @crossChannelMerge.
  ///
  /// In en, this message translates to:
  /// **'Merged across channels'**
  String get crossChannelMerge;

  /// No description provided for @sameItemMerged.
  ///
  /// In en, this message translates to:
  /// **'Same item appeared in {channels}; merged into one'**
  String sameItemMerged(String channels);

  /// No description provided for @whyPushed.
  ///
  /// In en, this message translates to:
  /// **'Why you got this'**
  String get whyPushed;

  /// No description provided for @changedToType.
  ///
  /// In en, this message translates to:
  /// **'Changed to {type}'**
  String changedToType(String type);

  /// No description provided for @goWorkbench.
  ///
  /// In en, this message translates to:
  /// **'Open desk'**
  String get goWorkbench;

  /// No description provided for @changeTypeFailed.
  ///
  /// In en, this message translates to:
  /// **'Couldn’t change type; try again'**
  String get changeTypeFailed;

  /// No description provided for @notImportantToast.
  ///
  /// In en, this message translates to:
  /// **'Lowered this source’s weight; suggestions will adapt'**
  String get notImportantToast;

  /// No description provided for @copiedTitleLink.
  ///
  /// In en, this message translates to:
  /// **'Title and link copied'**
  String get copiedTitleLink;

  /// No description provided for @changeTypeCurrent.
  ///
  /// In en, this message translates to:
  /// **'Change type (now {type})'**
  String changeTypeCurrent(String type);

  /// No description provided for @completed.
  ///
  /// In en, this message translates to:
  /// **'Completed'**
  String get completed;

  /// No description provided for @manuallyCorrected.
  ///
  /// In en, this message translates to:
  /// **'(manually corrected)'**
  String get manuallyCorrected;

  /// No description provided for @editHistory.
  ///
  /// In en, this message translates to:
  /// **'Edit history'**
  String get editHistory;

  /// No description provided for @versionsCount.
  ///
  /// In en, this message translates to:
  /// **'{count} versions'**
  String versionsCount(int count);

  /// No description provided for @firstSeen.
  ///
  /// In en, this message translates to:
  /// **'First seen'**
  String get firstSeen;

  /// No description provided for @contentUpdated.
  ///
  /// In en, this message translates to:
  /// **'Content updated'**
  String get contentUpdated;

  /// No description provided for @noDeadlines.
  ///
  /// In en, this message translates to:
  /// **'No deadlines'**
  String get noDeadlines;

  /// No description provided for @unreadStatus.
  ///
  /// In en, this message translates to:
  /// **'Unread'**
  String get unreadStatus;

  /// No description provided for @attachmentsCount.
  ///
  /// In en, this message translates to:
  /// **'{count} attachments'**
  String attachmentsCount(int count);

  /// No description provided for @deskEmptyToday.
  ///
  /// In en, this message translates to:
  /// **'Nothing urgent today'**
  String get deskEmptyToday;

  /// No description provided for @deskEmptyFilter.
  ///
  /// In en, this message translates to:
  /// **'No {filter}'**
  String deskEmptyFilter(String filter);

  /// No description provided for @statusChanged.
  ///
  /// In en, this message translates to:
  /// **'Changed'**
  String get statusChanged;

  /// No description provided for @statusUrgent.
  ///
  /// In en, this message translates to:
  /// **'Urgent'**
  String get statusUrgent;

  /// No description provided for @sourceNeedLoginNamed.
  ///
  /// In en, this message translates to:
  /// **'“{name}” needs sign-in again'**
  String sourceNeedLoginNamed(String name);

  /// No description provided for @sourceCheckFailedNamed.
  ///
  /// In en, this message translates to:
  /// **'“{name}” check failed'**
  String sourceCheckFailedNamed(String name);

  /// No description provided for @andMoreItems.
  ///
  /// In en, this message translates to:
  /// **'+{count} more'**
  String andMoreItems(int count);

  /// No description provided for @summaryLlmHint.
  ///
  /// In en, this message translates to:
  /// **'Generated by model · guidance only; original text wins'**
  String get summaryLlmHint;

  /// No description provided for @summaryRuleHint.
  ///
  /// In en, this message translates to:
  /// **'Rule extract · guidance only; original text wins'**
  String get summaryRuleHint;

  /// No description provided for @attachments.
  ///
  /// In en, this message translates to:
  /// **'Attachments'**
  String get attachments;

  /// No description provided for @sourceRawFields.
  ///
  /// In en, this message translates to:
  /// **'Source fields'**
  String get sourceRawFields;

  /// No description provided for @sfCourse.
  ///
  /// In en, this message translates to:
  /// **'Course'**
  String get sfCourse;

  /// No description provided for @sfSemester.
  ///
  /// In en, this message translates to:
  /// **'Term'**
  String get sfSemester;

  /// No description provided for @sfWeek.
  ///
  /// In en, this message translates to:
  /// **'Week'**
  String get sfWeek;

  /// No description provided for @sfWeekday.
  ///
  /// In en, this message translates to:
  /// **'Weekday'**
  String get sfWeekday;

  /// No description provided for @sfPeriod.
  ///
  /// In en, this message translates to:
  /// **'Period'**
  String get sfPeriod;

  /// No description provided for @sfDatetime.
  ///
  /// In en, this message translates to:
  /// **'Original time'**
  String get sfDatetime;

  /// No description provided for @sfOffice.
  ///
  /// In en, this message translates to:
  /// **'Office'**
  String get sfOffice;

  /// No description provided for @sfDepartment.
  ///
  /// In en, this message translates to:
  /// **'Department'**
  String get sfDepartment;

  /// No description provided for @sfRole.
  ///
  /// In en, this message translates to:
  /// **'Role'**
  String get sfRole;

  /// No description provided for @sfPhone.
  ///
  /// In en, this message translates to:
  /// **'Phone'**
  String get sfPhone;

  /// No description provided for @sfEmail.
  ///
  /// In en, this message translates to:
  /// **'Email'**
  String get sfEmail;

  /// No description provided for @sfSubtype.
  ///
  /// In en, this message translates to:
  /// **'Category'**
  String get sfSubtype;

  /// No description provided for @conditionSourceCheck.
  ///
  /// In en, this message translates to:
  /// **'Conditional source check'**
  String get conditionSourceCheck;

  /// No description provided for @viewSourceCheckSettings.
  ///
  /// In en, this message translates to:
  /// **'View source & check settings'**
  String get viewSourceCheckSettings;

  /// No description provided for @browserSourceCheck.
  ///
  /// In en, this message translates to:
  /// **'Browser source check'**
  String get browserSourceCheck;

  /// No description provided for @snapshotOnlyNoBg.
  ///
  /// In en, this message translates to:
  /// **'Snapshot only · background check not supported'**
  String get snapshotOnlyNoBg;

  /// No description provided for @myNotes.
  ///
  /// In en, this message translates to:
  /// **'My notes (source updates won’t overwrite)'**
  String get myNotes;

  /// No description provided for @groupOverdue.
  ///
  /// In en, this message translates to:
  /// **'Overdue'**
  String get groupOverdue;

  /// No description provided for @groupNextWeek.
  ///
  /// In en, this message translates to:
  /// **'Next week'**
  String get groupNextWeek;

  /// No description provided for @groupLater.
  ///
  /// In en, this message translates to:
  /// **'Later'**
  String get groupLater;

  /// No description provided for @groupNoDeadline.
  ///
  /// In en, this message translates to:
  /// **'No deadline'**
  String get groupNoDeadline;

  /// No description provided for @assignments.
  ///
  /// In en, this message translates to:
  /// **'Assignments'**
  String get assignments;

  /// No description provided for @noAssignmentsYet.
  ///
  /// In en, this message translates to:
  /// **'No assignments yet'**
  String get noAssignmentsYet;

  /// No description provided for @doneCount.
  ///
  /// In en, this message translates to:
  /// **'{count} completed'**
  String doneCount(int count);

  /// No description provided for @noNotices.
  ///
  /// In en, this message translates to:
  /// **'No notices'**
  String get noNotices;

  /// No description provided for @statusPending.
  ///
  /// In en, this message translates to:
  /// **'Open'**
  String get statusPending;

  /// No description provided for @courseNeedNetwork.
  ///
  /// In en, this message translates to:
  /// **'Course info needs a network connection'**
  String get courseNeedNetwork;

  /// No description provided for @courseNotFound.
  ///
  /// In en, this message translates to:
  /// **'Course not found'**
  String get courseNotFound;

  /// No description provided for @backToCourses.
  ///
  /// In en, this message translates to:
  /// **'Back to courses'**
  String get backToCourses;

  /// No description provided for @markReadShort.
  ///
  /// In en, this message translates to:
  /// **'Mark read'**
  String get markReadShort;

  /// No description provided for @markUnreadShort.
  ///
  /// In en, this message translates to:
  /// **'Mark unread'**
  String get markUnreadShort;

  /// No description provided for @addTodo.
  ///
  /// In en, this message translates to:
  /// **'Add to-do'**
  String get addTodo;

  /// No description provided for @removeTodo.
  ///
  /// In en, this message translates to:
  /// **'Remove to-do'**
  String get removeTodo;

  /// No description provided for @calMonth.
  ///
  /// In en, this message translates to:
  /// **'Month'**
  String get calMonth;

  /// No description provided for @calTwoWeeks.
  ///
  /// In en, this message translates to:
  /// **'2 weeks'**
  String get calTwoWeeks;

  /// No description provided for @calWeek.
  ///
  /// In en, this message translates to:
  /// **'Week'**
  String get calWeek;

  /// No description provided for @brandFallback.
  ///
  /// In en, this message translates to:
  /// **'CR'**
  String get brandFallback;

  /// No description provided for @bcNotExecuted.
  ///
  /// In en, this message translates to:
  /// **'Awaiting first check'**
  String get bcNotExecuted;

  /// No description provided for @bcUnchanged.
  ///
  /// In en, this message translates to:
  /// **'Check OK · no change'**
  String get bcUnchanged;

  /// No description provided for @bcChanged.
  ///
  /// In en, this message translates to:
  /// **'Source changed'**
  String get bcChanged;

  /// No description provided for @bcNeedLogin.
  ///
  /// In en, this message translates to:
  /// **'Sign in again on the school site'**
  String get bcNeedLogin;

  /// No description provided for @bcAccountMismatch.
  ///
  /// In en, this message translates to:
  /// **'School account switched · old binding stopped'**
  String get bcAccountMismatch;

  /// No description provided for @bcSelectionMissing.
  ///
  /// In en, this message translates to:
  /// **'Original selection lost · recapture needed'**
  String get bcSelectionMissing;

  /// No description provided for @bcViewMismatch.
  ///
  /// In en, this message translates to:
  /// **'Term/week view invalid · recapture needed'**
  String get bcViewMismatch;

  /// No description provided for @bcRouteMismatch.
  ///
  /// In en, this message translates to:
  /// **'Source route changed · recapture needed'**
  String get bcRouteMismatch;

  /// No description provided for @bcRenderTimeout.
  ///
  /// In en, this message translates to:
  /// **'Page load timed out'**
  String get bcRenderTimeout;

  /// No description provided for @bcPermissionDenied.
  ///
  /// In en, this message translates to:
  /// **'Browser source permission denied'**
  String get bcPermissionDenied;

  /// No description provided for @bcUnsupported.
  ///
  /// In en, this message translates to:
  /// **'Monitoring not supported'**
  String get bcUnsupported;

  /// No description provided for @bcFailed.
  ///
  /// In en, this message translates to:
  /// **'Check failed'**
  String get bcFailed;

  /// No description provided for @rrRejected.
  ///
  /// In en, this message translates to:
  /// **'Check result rejected · data kept, monitoring paused'**
  String get rrRejected;

  /// No description provided for @rrPurged.
  ///
  /// In en, this message translates to:
  /// **'Linked docs deleted · extract again from the page'**
  String get rrPurged;

  /// No description provided for @rrStarting.
  ///
  /// In en, this message translates to:
  /// **'Auto-monitor starting · waiting for first refresh'**
  String get rrStarting;

  /// No description provided for @rrProtocolUnavailable.
  ///
  /// In en, this message translates to:
  /// **'The local backend is temporarily unable to read this page'**
  String get rrProtocolUnavailable;

  /// No description provided for @rrProtocolAccountRequired.
  ///
  /// In en, this message translates to:
  /// **'Verify the website account used by the local session'**
  String get rrProtocolAccountRequired;

  /// No description provided for @rrProtocolUnsupported.
  ///
  /// In en, this message translates to:
  /// **'This page needs to be read in the browser'**
  String get rrProtocolUnsupported;

  /// No description provided for @rrWaitingPage.
  ///
  /// In en, this message translates to:
  /// **'Waiting for the monitored page to reopen'**
  String get rrWaitingPage;

  /// No description provided for @rrUserBusy.
  ///
  /// In en, this message translates to:
  /// **'Monitor page is being edited · refresh deferred'**
  String get rrUserBusy;

  /// No description provided for @rrTabMissing.
  ///
  /// In en, this message translates to:
  /// **'Monitor tab closed · open the page and rebind'**
  String get rrTabMissing;

  /// No description provided for @rrTabRebind.
  ///
  /// In en, this message translates to:
  /// **'Browser session restarted · rebind the monitor tab'**
  String get rrTabRebind;

  /// No description provided for @rrTabAmbiguous.
  ///
  /// In en, this message translates to:
  /// **'Multiple same pages open · keep one monitor tab'**
  String get rrTabAmbiguous;

  /// No description provided for @rrSingleAccount.
  ///
  /// In en, this message translates to:
  /// **'Another account bound on this site · paused'**
  String get rrSingleAccount;

  /// No description provided for @rrRestored.
  ///
  /// In en, this message translates to:
  /// **'Source restored · check paused until retested'**
  String get rrRestored;

  /// No description provided for @rrDocsRestored.
  ///
  /// In en, this message translates to:
  /// **'Docs restored · source check still paused'**
  String get rrDocsRestored;

  /// No description provided for @rrDocsTrashed.
  ///
  /// In en, this message translates to:
  /// **'Linked docs moved to trash · check paused'**
  String get rrDocsTrashed;

  /// No description provided for @rrPrivateRequired.
  ///
  /// In en, this message translates to:
  /// **'Login detected · recapture as a signed-in source'**
  String get rrPrivateRequired;

  /// No description provided for @rrVerified.
  ///
  /// In en, this message translates to:
  /// **'Reread verified · awaiting check'**
  String get rrVerified;

  /// No description provided for @rrAccountUnknown.
  ///
  /// In en, this message translates to:
  /// **'Cannot verify source account · keep manual capture'**
  String get rrAccountUnknown;

  /// No description provided for @rrAccountMismatch.
  ///
  /// In en, this message translates to:
  /// **'Source account mismatch · paused'**
  String get rrAccountMismatch;

  /// No description provided for @rrNoMatch.
  ///
  /// In en, this message translates to:
  /// **'No match this time · kept previous data'**
  String get rrNoMatch;

  /// No description provided for @rrPreviewOnly.
  ///
  /// In en, this message translates to:
  /// **'Incomplete content · data not overwritten'**
  String get rrPreviewOnly;

  /// No description provided for @rrUnsupported.
  ///
  /// In en, this message translates to:
  /// **'Background reread not supported'**
  String get rrUnsupported;

  /// No description provided for @rrWorkerInterrupted.
  ///
  /// In en, this message translates to:
  /// **'Browser task interrupted · retry'**
  String get rrWorkerInterrupted;

  /// No description provided for @deadlineCalendar.
  ///
  /// In en, this message translates to:
  /// **'Deadline calendar'**
  String get deadlineCalendar;

  /// No description provided for @rsExpired.
  ///
  /// In en, this message translates to:
  /// **'Check timed out · waiting for browser retry'**
  String get rsExpired;

  /// No description provided for @rsQueued.
  ///
  /// In en, this message translates to:
  /// **'Queued · waiting to run'**
  String get rsQueued;

  /// No description provided for @rsChecking.
  ///
  /// In en, this message translates to:
  /// **'Checking in browser'**
  String get rsChecking;

  /// No description provided for @rsWaitChrome.
  ///
  /// In en, this message translates to:
  /// **'Waiting for local Chrome'**
  String get rsWaitChrome;

  /// No description provided for @rsLoginReuse.
  ///
  /// In en, this message translates to:
  /// **'Reuse current Chrome session (confirmed)'**
  String get rsLoginReuse;

  /// No description provided for @rsLoginNone.
  ///
  /// In en, this message translates to:
  /// **'No login required (declared)'**
  String get rsLoginNone;

  /// No description provided for @rsLoginRequired.
  ///
  /// In en, this message translates to:
  /// **'Login required'**
  String get rsLoginRequired;

  /// No description provided for @rsIdResidentGeneric.
  ///
  /// In en, this message translates to:
  /// **'Dedicated monitor tab · single-account session'**
  String get rsIdResidentGeneric;

  /// No description provided for @rsIdResidentSchool.
  ///
  /// In en, this message translates to:
  /// **'School account · dedicated monitor tab'**
  String get rsIdResidentSchool;

  /// No description provided for @rsIdPublic.
  ///
  /// In en, this message translates to:
  /// **'No login (user declared)'**
  String get rsIdPublic;

  /// No description provided for @rsAccountUnchecked.
  ///
  /// In en, this message translates to:
  /// **'account unchecked'**
  String get rsAccountUnchecked;

  /// No description provided for @rsIdSchoolChrome.
  ///
  /// In en, this message translates to:
  /// **'School account · local Chrome'**
  String get rsIdSchoolChrome;

  /// No description provided for @rsTitleTimeline.
  ///
  /// In en, this message translates to:
  /// **'Moodle activity summary'**
  String get rsTitleTimeline;

  /// No description provided for @rsTitleTeacher.
  ///
  /// In en, this message translates to:
  /// **'Faculty profile'**
  String get rsTitleTeacher;

  /// No description provided for @rsTitleWeb.
  ///
  /// In en, this message translates to:
  /// **'Web clip'**
  String get rsTitleWeb;

  /// No description provided for @rsScopeTitle.
  ///
  /// In en, this message translates to:
  /// **'Title and link titles'**
  String get rsScopeTitle;

  /// No description provided for @rsScopeTimeline.
  ///
  /// In en, this message translates to:
  /// **'Loaded activities · full summary set'**
  String get rsScopeTimeline;

  /// No description provided for @rsScopeBody.
  ///
  /// In en, this message translates to:
  /// **'Body and lists · full match set'**
  String get rsScopeBody;

  /// No description provided for @rsScopeOriginal.
  ///
  /// In en, this message translates to:
  /// **'Original conditions and agreed view'**
  String get rsScopeOriginal;

  /// No description provided for @rsWaitLocalChrome.
  ///
  /// In en, this message translates to:
  /// **'Waiting for local Chrome'**
  String get rsWaitLocalChrome;

  /// No description provided for @rsStartingCheck.
  ///
  /// In en, this message translates to:
  /// **'Starting / checking'**
  String get rsStartingCheck;

  /// No description provided for @rsPeriodicPaused.
  ///
  /// In en, this message translates to:
  /// **'Periodic monitoring paused'**
  String get rsPeriodicPaused;

  /// No description provided for @rsPartialPaused.
  ///
  /// In en, this message translates to:
  /// **'Some rules paused'**
  String get rsPartialPaused;

  /// No description provided for @rsPeriodicOn.
  ///
  /// In en, this message translates to:
  /// **'Periodic monitoring on'**
  String get rsPeriodicOn;

  /// No description provided for @rsManualOnly.
  ///
  /// In en, this message translates to:
  /// **'Manual check only'**
  String get rsManualOnly;

  /// No description provided for @rsAwaitFirstRefresh.
  ///
  /// In en, this message translates to:
  /// **'Waiting for first refresh'**
  String get rsAwaitFirstRefresh;

  /// No description provided for @rsDedicatedMonitor.
  ///
  /// In en, this message translates to:
  /// **'Dedicated monitor page'**
  String get rsDedicatedMonitor;

  /// No description provided for @labelCreated.
  ///
  /// In en, this message translates to:
  /// **'Created “{name}”'**
  String labelCreated(String name);

  /// No description provided for @labelDeleted.
  ///
  /// In en, this message translates to:
  /// **'Deleted “{name}”'**
  String labelDeleted(String name);

  /// No description provided for @deleteLabelTitle.
  ///
  /// In en, this message translates to:
  /// **'Delete “{name}”?'**
  String deleteLabelTitle(String name);

  /// No description provided for @deleteLabelBody.
  ///
  /// In en, this message translates to:
  /// **'This label will be removed from items. Stars are unchanged.'**
  String get deleteLabelBody;

  /// No description provided for @actionDelete.
  ///
  /// In en, this message translates to:
  /// **'Delete'**
  String get actionDelete;

  /// No description provided for @searchInboxHint.
  ///
  /// In en, this message translates to:
  /// **'Search title, course, or source'**
  String get searchInboxHint;

  /// No description provided for @inboxEmptyFilter.
  ///
  /// In en, this message translates to:
  /// **'No items for this filter'**
  String get inboxEmptyFilter;

  /// No description provided for @tagItem.
  ///
  /// In en, this message translates to:
  /// **'Label this item'**
  String get tagItem;

  /// No description provided for @loadingLabels.
  ///
  /// In en, this message translates to:
  /// **'Loading labels'**
  String get loadingLabels;

  /// No description provided for @labelsLoadFailed.
  ///
  /// In en, this message translates to:
  /// **'Couldn’t load labels'**
  String get labelsLoadFailed;

  /// No description provided for @retry.
  ///
  /// In en, this message translates to:
  /// **'Retry'**
  String get retry;

  /// No description provided for @noLabelsYet.
  ///
  /// In en, this message translates to:
  /// **'No labels yet. Create one first.'**
  String get noLabelsYet;

  /// No description provided for @newLabelAction.
  ///
  /// In en, this message translates to:
  /// **'New label'**
  String get newLabelAction;

  /// No description provided for @labelNameHint.
  ///
  /// In en, this message translates to:
  /// **'e.g. Starred, Homework, Club'**
  String get labelNameHint;

  /// No description provided for @color.
  ///
  /// In en, this message translates to:
  /// **'Color'**
  String get color;

  /// No description provided for @create.
  ///
  /// In en, this message translates to:
  /// **'Create'**
  String get create;

  /// No description provided for @movedToTrash.
  ///
  /// In en, this message translates to:
  /// **'Moved to trash. Content and history kept.'**
  String get movedToTrash;

  /// No description provided for @restoredItem.
  ///
  /// In en, this message translates to:
  /// **'Restored. Source checks stay paused.'**
  String get restoredItem;

  /// No description provided for @undo.
  ///
  /// In en, this message translates to:
  /// **'Undo'**
  String get undo;

  /// No description provided for @accountChanged.
  ///
  /// In en, this message translates to:
  /// **'Desk account changed'**
  String get accountChanged;

  /// No description provided for @restoreIncomplete.
  ///
  /// In en, this message translates to:
  /// **'Restore incomplete: {error}'**
  String restoreIncomplete(String error);

  /// No description provided for @actionUnconfirmed.
  ///
  /// In en, this message translates to:
  /// **'Action not confirmed: {error}'**
  String actionUnconfirmed(String error);

  /// No description provided for @restoreToInbox.
  ///
  /// In en, this message translates to:
  /// **'Restore to inbox'**
  String get restoreToInbox;

  /// No description provided for @moveToTrash.
  ///
  /// In en, this message translates to:
  /// **'Move to trash'**
  String get moveToTrash;

  /// No description provided for @cannotOpenItem.
  ///
  /// In en, this message translates to:
  /// **'Can’t open this item'**
  String get cannotOpenItem;

  /// No description provided for @itemNotFound.
  ///
  /// In en, this message translates to:
  /// **'Item missing or not yours. Use the same Gleaner account in desk and extension.'**
  String get itemNotFound;

  /// No description provided for @loginExpired.
  ///
  /// In en, this message translates to:
  /// **'Session expired. Sign in again on the desk.'**
  String get loginExpired;

  /// No description provided for @detailLoadFailed.
  ///
  /// In en, this message translates to:
  /// **'Couldn’t load details. Check the backend and retry.'**
  String get detailLoadFailed;

  /// No description provided for @currentDeskAccount.
  ///
  /// In en, this message translates to:
  /// **'Current desk account: {email}'**
  String currentDeskAccount(String email);

  /// No description provided for @notSignedIn.
  ///
  /// In en, this message translates to:
  /// **'Not signed in'**
  String get notSignedIn;

  /// No description provided for @backToSources.
  ///
  /// In en, this message translates to:
  /// **'Back to sources'**
  String get backToSources;

  /// No description provided for @notProvided.
  ///
  /// In en, this message translates to:
  /// **'Not provided'**
  String get notProvided;

  /// No description provided for @sourceDeadline.
  ///
  /// In en, this message translates to:
  /// **'Source deadline'**
  String get sourceDeadline;

  /// No description provided for @submitRequirements.
  ///
  /// In en, this message translates to:
  /// **'Submission requirements'**
  String get submitRequirements;

  /// No description provided for @sourceFields.
  ///
  /// In en, this message translates to:
  /// **'Source fields'**
  String get sourceFields;

  /// No description provided for @beforeChange.
  ///
  /// In en, this message translates to:
  /// **'Before:\n{value}'**
  String beforeChange(String value);

  /// No description provided for @afterChange.
  ///
  /// In en, this message translates to:
  /// **'After:\n{value}'**
  String afterChange(String value);

  /// No description provided for @timelineMaterial.
  ///
  /// In en, this message translates to:
  /// **'Activity summary · {count} activities'**
  String timelineMaterial(int count);

  /// No description provided for @webSnapshot.
  ///
  /// In en, this message translates to:
  /// **'Web snapshot · {count} fragments'**
  String webSnapshot(int count);

  /// No description provided for @activityN.
  ///
  /// In en, this message translates to:
  /// **'Activity {n}: {title}'**
  String activityN(int n, String title);

  /// No description provided for @fragmentN.
  ///
  /// In en, this message translates to:
  /// **'Fragment {n}: {title}'**
  String fragmentN(int n, String title);

  /// No description provided for @openActivity.
  ///
  /// In en, this message translates to:
  /// **'Open activity'**
  String get openActivity;

  /// No description provided for @courseField.
  ///
  /// In en, this message translates to:
  /// **'Course: {value}'**
  String courseField(String value);

  /// No description provided for @wcCond.
  ///
  /// In en, this message translates to:
  /// **'Query: {value}'**
  String wcCond(String value);

  /// No description provided for @wcIdentitySchool.
  ///
  /// In en, this message translates to:
  /// **'Source identity: school account · local Chrome'**
  String get wcIdentitySchool;

  /// No description provided for @wcScopeTimeline.
  ///
  /// In en, this message translates to:
  /// **'Scope: currently loaded Timeline activities'**
  String get wcScopeTimeline;

  /// No description provided for @wcMatchTitle.
  ///
  /// In en, this message translates to:
  /// **'Match: titles and link titles'**
  String get wcMatchTitle;

  /// No description provided for @wcMatchBody.
  ///
  /// In en, this message translates to:
  /// **'Match: body and lists'**
  String get wcMatchBody;

  /// No description provided for @wcAlias.
  ///
  /// In en, this message translates to:
  /// **'Source alias: {value}'**
  String wcAlias(String value);

  /// No description provided for @wcLoginNone.
  ///
  /// In en, this message translates to:
  /// **'Site login: not required (user declared)'**
  String get wcLoginNone;

  /// No description provided for @wcLoginRequired.
  ///
  /// In en, this message translates to:
  /// **'Site login: required'**
  String get wcLoginRequired;

  /// No description provided for @wcAccount.
  ///
  /// In en, this message translates to:
  /// **'Source account: {value}'**
  String wcAccount(String value);

  /// No description provided for @wcAccountUnchecked.
  ///
  /// In en, this message translates to:
  /// **'unchecked'**
  String get wcAccountUnchecked;

  /// No description provided for @wcPrivateOnly.
  ///
  /// In en, this message translates to:
  /// **'Visibility: only me'**
  String get wcPrivateOnly;

  /// No description provided for @wcTimelineHint.
  ///
  /// In en, this message translates to:
  /// **'Activity reminder summary only; detail bodies were not read. Dates/times stay as original text; missing values are not guessed.'**
  String get wcTimelineHint;

  /// No description provided for @wcLinkedHint.
  ///
  /// In en, this message translates to:
  /// **'Matched fragments in the agreed view only—not a full article or email. Linked to a source; check method and status under Sources.'**
  String get wcLinkedHint;

  /// No description provided for @wcUnlinkedHint.
  ///
  /// In en, this message translates to:
  /// **'Currently loaded content only—not a full article or email. Alias is user-declared; source checks are off.'**
  String get wcUnlinkedHint;

  /// No description provided for @wcUpdateOnChange.
  ///
  /// In en, this message translates to:
  /// **'When a check succeeds and content changes, the same item’s source version updates; personal notes and status stay.'**
  String get wcUpdateOnChange;

  /// No description provided for @wcUpdateOnRecapture.
  ///
  /// In en, this message translates to:
  /// **'Re-extract and save with the same source tag, URL, query, and scope to update this item’s version.'**
  String get wcUpdateOnRecapture;

  /// No description provided for @wcDateText.
  ///
  /// In en, this message translates to:
  /// **'Date text: {value}'**
  String wcDateText(String value);

  /// No description provided for @wcTimeText.
  ///
  /// In en, this message translates to:
  /// **'Time text: {value}'**
  String wcTimeText(String value);

  /// No description provided for @wcDomEvidence.
  ///
  /// In en, this message translates to:
  /// **'DOM evidence: {value}'**
  String wcDomEvidence(String value);

  /// No description provided for @aliasMissing.
  ///
  /// In en, this message translates to:
  /// **'not provided'**
  String get aliasMissing;

  /// No description provided for @changeNoteSep.
  ///
  /// In en, this message translates to:
  /// **'; '**
  String get changeNoteSep;

  /// No description provided for @changeNameSep.
  ///
  /// In en, this message translates to:
  /// **', '**
  String get changeNameSep;

  /// No description provided for @changeDays.
  ///
  /// In en, this message translates to:
  /// **'{count} d'**
  String changeDays(int count);

  /// No description provided for @changeHours.
  ///
  /// In en, this message translates to:
  /// **'{count} h'**
  String changeHours(int count);

  /// No description provided for @changeDeadlineAdvanced.
  ///
  /// In en, this message translates to:
  /// **'Deadline moved earlier by {span} ({from} → {to})'**
  String changeDeadlineAdvanced(String span, String from, String to);

  /// No description provided for @changeDeadlinePostponed.
  ///
  /// In en, this message translates to:
  /// **'Deadline postponed by {span} ({from} → {to})'**
  String changeDeadlinePostponed(String span, String from, String to);

  /// No description provided for @changeDeadlineAdded.
  ///
  /// In en, this message translates to:
  /// **'Deadline added {when}'**
  String changeDeadlineAdded(String when);

  /// No description provided for @changeDeadlineRemoved.
  ///
  /// In en, this message translates to:
  /// **'Deadline removed'**
  String get changeDeadlineRemoved;

  /// No description provided for @changeAttachmentReplaced.
  ///
  /// In en, this message translates to:
  /// **'Attachments replaced: {names}'**
  String changeAttachmentReplaced(String names);

  /// No description provided for @changeAttachmentAdded.
  ///
  /// In en, this message translates to:
  /// **'Attachments added: {names}'**
  String changeAttachmentAdded(String names);

  /// No description provided for @changeAttachmentRemoved.
  ///
  /// In en, this message translates to:
  /// **'Attachments removed: {names}'**
  String changeAttachmentRemoved(String names);

  /// No description provided for @changeAttachmentUpdated.
  ///
  /// In en, this message translates to:
  /// **'Attachment content updated'**
  String get changeAttachmentUpdated;

  /// No description provided for @changeRequirements.
  ///
  /// In en, this message translates to:
  /// **'Submission requirements changed'**
  String get changeRequirements;

  /// No description provided for @changeEventTime.
  ///
  /// In en, this message translates to:
  /// **'Event time changed'**
  String get changeEventTime;

  /// No description provided for @changeLocation.
  ///
  /// In en, this message translates to:
  /// **'Location changed'**
  String get changeLocation;

  /// No description provided for @changeType.
  ///
  /// In en, this message translates to:
  /// **'Type changed'**
  String get changeType;

  /// No description provided for @changeTitle.
  ///
  /// In en, this message translates to:
  /// **'Title changed'**
  String get changeTitle;

  /// No description provided for @changeWording.
  ///
  /// In en, this message translates to:
  /// **'Wording updated'**
  String get changeWording;

  /// No description provided for @sourceSessionExpired.
  ///
  /// In en, this message translates to:
  /// **'Session expired. Sign in again under Sources.'**
  String get sourceSessionExpired;

  /// No description provided for @eventReminder.
  ///
  /// In en, this message translates to:
  /// **'Deadline reminder'**
  String get eventReminder;

  /// No description provided for @eventImportantChange.
  ///
  /// In en, this message translates to:
  /// **'Important change'**
  String get eventImportantChange;

  /// No description provided for @eventNewItem.
  ///
  /// In en, this message translates to:
  /// **'New item'**
  String get eventNewItem;

  /// No description provided for @digestTitle.
  ///
  /// In en, this message translates to:
  /// **'Daily digest'**
  String get digestTitle;

  /// No description provided for @digestBody.
  ///
  /// In en, this message translates to:
  /// **'Past 24 hours: {newCount} new items, {upcoming} due soon'**
  String digestBody(int newCount, int upcoming);

  /// No description provided for @reasonBlocked.
  ///
  /// In en, this message translates to:
  /// **'Matched a blocked word'**
  String get reasonBlocked;

  /// No description provided for @reasonKeyword.
  ///
  /// In en, this message translates to:
  /// **'Keywords: {words}'**
  String reasonKeyword(String words);

  /// No description provided for @reasonDue24h.
  ///
  /// In en, this message translates to:
  /// **'Due within 24 hours'**
  String get reasonDue24h;

  /// No description provided for @reasonDue7d.
  ///
  /// In en, this message translates to:
  /// **'Due within 7 days'**
  String get reasonDue7d;

  /// No description provided for @reasonYourCourse.
  ///
  /// In en, this message translates to:
  /// **'Your course'**
  String get reasonYourCourse;

  /// No description provided for @reasonCourseItem.
  ///
  /// In en, this message translates to:
  /// **'Course item'**
  String get reasonCourseItem;

  /// No description provided for @reasonGradeMajorMatch.
  ///
  /// In en, this message translates to:
  /// **'Matches your year/major'**
  String get reasonGradeMajorMatch;

  /// No description provided for @reasonOtherAudience.
  ///
  /// In en, this message translates to:
  /// **'For another year or major'**
  String get reasonOtherAudience;

  /// No description provided for @reasonImportantChange.
  ///
  /// In en, this message translates to:
  /// **'Important change'**
  String get reasonImportantChange;

  /// No description provided for @errMoodleNeedLogin.
  ///
  /// In en, this message translates to:
  /// **'Not signed into this Moodle source yet'**
  String get errMoodleNeedLogin;

  /// No description provided for @courseOpenCount.
  ///
  /// In en, this message translates to:
  /// **'Open'**
  String get courseOpenCount;

  /// No description provided for @noCoursesYet.
  ///
  /// In en, this message translates to:
  /// **'No courses yet'**
  String get noCoursesYet;

  /// No description provided for @noCoursesHint.
  ///
  /// In en, this message translates to:
  /// **'Add a Moodle source to get a home page per course. Add the Faculty directory template for office and email.'**
  String get noCoursesHint;

  /// No description provided for @noCourseTodos.
  ///
  /// In en, this message translates to:
  /// **'Nothing open'**
  String get noCourseTodos;

  /// No description provided for @addFacultySourceHint.
  ///
  /// In en, this message translates to:
  /// **'Add a Faculty directory source to show teacher contacts'**
  String get addFacultySourceHint;

  /// No description provided for @captureFromWeb.
  ///
  /// In en, this message translates to:
  /// **'Capture from web'**
  String get captureFromWeb;

  /// No description provided for @refreshSourceListTooltip.
  ///
  /// In en, this message translates to:
  /// **'Refresh list status (does not open source pages)'**
  String get refreshSourceListTooltip;

  /// No description provided for @cannotReadSources.
  ///
  /// In en, this message translates to:
  /// **'Could not read sources'**
  String get cannotReadSources;

  /// No description provided for @savedPages.
  ///
  /// In en, this message translates to:
  /// **'Saved pages'**
  String get savedPages;

  /// No description provided for @periodicRules.
  ///
  /// In en, this message translates to:
  /// **'Periodic rules'**
  String get periodicRules;

  /// No description provided for @needsAttention.
  ///
  /// In en, this message translates to:
  /// **'Needs attention'**
  String get needsAttention;

  /// No description provided for @changesFound.
  ///
  /// In en, this message translates to:
  /// **'Changes found'**
  String get changesFound;

  /// No description provided for @mySources.
  ///
  /// In en, this message translates to:
  /// **'My sources'**
  String get mySources;

  /// No description provided for @noReadingSources.
  ///
  /// In en, this message translates to:
  /// **'No sources with saved conditions yet. Extract, preview, and save from the original page with the extension.'**
  String get noReadingSources;

  /// No description provided for @monitorTabHint.
  ///
  /// In en, this message translates to:
  /// **'Keep the dedicated monitoring tab open; you can close the desk page. Keep Chrome, the extension, and the local service running—checks may be delayed.'**
  String get monitorTabHint;

  /// No description provided for @deletedSourcesTitle.
  ///
  /// In en, this message translates to:
  /// **'Deleted sources ({count})'**
  String deletedSourcesTitle(int count);

  /// No description provided for @deletedSourcesSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Restored sources stay paused; permanent delete clears linked docs and history.'**
  String get deletedSourcesSubtitle;

  /// No description provided for @deletedSourcesUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Deleted sources unavailable: {error}'**
  String deletedSourcesUnavailable(String error);

  /// No description provided for @legacyDemoTitle.
  ///
  /// In en, this message translates to:
  /// **'Legacy data & demo subscriptions'**
  String get legacyDemoTitle;

  /// No description provided for @legacyDemoSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Existing data is kept; if conditions are missing, open the original page and capture again.'**
  String get legacyDemoSubtitle;

  /// No description provided for @chromeConnectedHint.
  ///
  /// In en, this message translates to:
  /// **'Local Chrome connected recently · original-site sign-in is checked per source'**
  String get chromeConnectedHint;

  /// No description provided for @chromeDisconnectedHint.
  ///
  /// In en, this message translates to:
  /// **'No recent executor connection · last successful results kept'**
  String get chromeDisconnectedHint;

  /// No description provided for @checkQueued.
  ///
  /// In en, this message translates to:
  /// **'Check queued; status updates after confirmation.'**
  String get checkQueued;

  /// No description provided for @periodicResumed.
  ///
  /// In en, this message translates to:
  /// **'Periodic checks resumed.'**
  String get periodicResumed;

  /// No description provided for @periodicPaused.
  ///
  /// In en, this message translates to:
  /// **'Periodic checks paused; manual checks still work.'**
  String get periodicPaused;

  /// No description provided for @pageCheckQueued.
  ///
  /// In en, this message translates to:
  /// **'Full-page check queued; rules on the same page share the refresh.'**
  String get pageCheckQueued;

  /// No description provided for @pagePlanUpdated.
  ///
  /// In en, this message translates to:
  /// **'Full-page monitoring plan updated.'**
  String get pagePlanUpdated;

  /// No description provided for @sourceDeletedKeep.
  ///
  /// In en, this message translates to:
  /// **'Source deleted; docs and history kept.'**
  String get sourceDeletedKeep;

  /// No description provided for @sourceDeletedTrash.
  ///
  /// In en, this message translates to:
  /// **'Source deleted; linked docs moved to trash.'**
  String get sourceDeletedTrash;

  /// No description provided for @deleteSourceTitle.
  ///
  /// In en, this message translates to:
  /// **'Delete this source?'**
  String get deleteSourceTitle;

  /// No description provided for @deleteSourceBody.
  ///
  /// In en, this message translates to:
  /// **'Stops manual and periodic checks. Saved docs, notes, and history stay by default. Restore from Deleted sources; old jobs won’t auto-resume.'**
  String get deleteSourceBody;

  /// No description provided for @deleteSourceAlsoTrash.
  ///
  /// In en, this message translates to:
  /// **'Also move linked docs to personal trash'**
  String get deleteSourceAlsoTrash;

  /// No description provided for @deleteSourceAlsoTrashHint.
  ///
  /// In en, this message translates to:
  /// **'Also hides them in other sources that reference them; restore from Inbox trash.'**
  String get deleteSourceAlsoTrashHint;

  /// No description provided for @deleteSourceAction.
  ///
  /// In en, this message translates to:
  /// **'Delete source'**
  String get deleteSourceAction;

  /// No description provided for @restoreSourceAction.
  ///
  /// In en, this message translates to:
  /// **'Restore source'**
  String get restoreSourceAction;

  /// No description provided for @purgeForever.
  ///
  /// In en, this message translates to:
  /// **'Delete permanently'**
  String get purgeForever;

  /// No description provided for @checkStoppedKept.
  ///
  /// In en, this message translates to:
  /// **'Checks stopped · docs and history kept as chosen'**
  String get checkStoppedKept;

  /// No description provided for @sourceRestoredPaused.
  ///
  /// In en, this message translates to:
  /// **'Source restored and paused; retest re-read.'**
  String get sourceRestoredPaused;

  /// No description provided for @manageLegacySources.
  ///
  /// In en, this message translates to:
  /// **'Manage legacy templates / demo sources'**
  String get manageLegacySources;

  /// No description provided for @legacyCaptureSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Legacy capture · not auto-migrated to condition monitoring'**
  String get legacyCaptureSubtitle;

  /// No description provided for @legacyCapturesFailed.
  ///
  /// In en, this message translates to:
  /// **'Could not read legacy data: {error}'**
  String legacyCapturesFailed(String error);

  /// No description provided for @statusRefreshFailed.
  ///
  /// In en, this message translates to:
  /// **'Status refresh failed: {error}'**
  String statusRefreshFailed(String error);

  /// No description provided for @profileTitle.
  ///
  /// In en, this message translates to:
  /// **'Profile'**
  String get profileTitle;

  /// No description provided for @coursesCommaHint.
  ///
  /// In en, this message translates to:
  /// **'My courses (comma-separated)'**
  String get coursesCommaHint;

  /// No description provided for @coursesHintSample.
  ///
  /// In en, this message translates to:
  /// **'Network Programming, Operating Systems'**
  String get coursesHintSample;

  /// No description provided for @gradeHintSample.
  ///
  /// In en, this message translates to:
  /// **'Class of 2024'**
  String get gradeHintSample;

  /// No description provided for @majorHintSample.
  ///
  /// In en, this message translates to:
  /// **'Computer Science'**
  String get majorHintSample;

  /// No description provided for @profileMatchHint.
  ///
  /// In en, this message translates to:
  /// **'Year, major, and courses help decide if a notice is relevant to you.'**
  String get profileMatchHint;

  /// No description provided for @quietStartHelp.
  ///
  /// In en, this message translates to:
  /// **'Do-not-disturb start'**
  String get quietStartHelp;

  /// No description provided for @quietEndHelp.
  ///
  /// In en, this message translates to:
  /// **'Do-not-disturb end'**
  String get quietEndHelp;

  /// No description provided for @digestTimeHelp.
  ///
  /// In en, this message translates to:
  /// **'Daily digest time'**
  String get digestTimeHelp;

  /// No description provided for @currentPassword.
  ///
  /// In en, this message translates to:
  /// **'Current password'**
  String get currentPassword;

  /// No description provided for @newPasswordMin8.
  ///
  /// In en, this message translates to:
  /// **'New password (at least 8 characters)'**
  String get newPasswordMin8;

  /// No description provided for @passwordChangedToast.
  ///
  /// In en, this message translates to:
  /// **'Password changed. Other devices need to sign in again.'**
  String get passwordChangedToast;

  /// No description provided for @confirmChangePassword.
  ///
  /// In en, this message translates to:
  /// **'Update password'**
  String get confirmChangePassword;

  /// No description provided for @deleteAccountTitle.
  ///
  /// In en, this message translates to:
  /// **'Delete account?'**
  String get deleteAccountTitle;

  /// No description provided for @deleteAccountBody.
  ///
  /// In en, this message translates to:
  /// **'This permanently deletes your account, subscriptions, sessions, personal state, and sent mail. Enter your password to confirm.'**
  String get deleteAccountBody;

  /// No description provided for @deleteForever.
  ///
  /// In en, this message translates to:
  /// **'Delete permanently'**
  String get deleteForever;

  /// No description provided for @rulesSavedToast.
  ///
  /// In en, this message translates to:
  /// **'Rules saved. They apply to new items going forward.'**
  String get rulesSavedToast;

  /// No description provided for @priorityFormula.
  ///
  /// In en, this message translates to:
  /// **'Priority = 100 × (0.30 source weight + 0.25 keywords + 0.25 deadline proximity + 0.20 match)'**
  String get priorityFormula;

  /// No description provided for @priorityBands.
  ///
  /// In en, this message translates to:
  /// **'≥ 80 urgent (push) · 40–79 normal · < 40 feed & digest only'**
  String get priorityBands;

  /// No description provided for @ruleKeyword.
  ///
  /// In en, this message translates to:
  /// **'Keywords'**
  String get ruleKeyword;

  /// No description provided for @ruleSenderWhitelist.
  ///
  /// In en, this message translates to:
  /// **'Sender allowlist'**
  String get ruleSenderWhitelist;

  /// No description provided for @ruleKeywordHint.
  ///
  /// In en, this message translates to:
  /// **'e.g. scholarship, internship'**
  String get ruleKeywordHint;

  /// No description provided for @ruleBlock.
  ///
  /// In en, this message translates to:
  /// **'Block'**
  String get ruleBlock;

  /// No description provided for @actionAdd.
  ///
  /// In en, this message translates to:
  /// **'Add'**
  String get actionAdd;

  /// No description provided for @noCustomRules.
  ///
  /// In en, this message translates to:
  /// **'No custom rules yet'**
  String get noCustomRules;

  /// No description provided for @defaultKeywordsHint.
  ///
  /// In en, this message translates to:
  /// **'Default keywords: deadline, exam, reschedule, cancel.'**
  String get defaultKeywordsHint;

  /// No description provided for @teachersHeader.
  ///
  /// In en, this message translates to:
  /// **'Faculty'**
  String get teachersHeader;

  /// No description provided for @orEnterPairCode.
  ///
  /// In en, this message translates to:
  /// **'Or enter a pairing code'**
  String get orEnterPairCode;

  /// No description provided for @pairCodeHint.
  ///
  /// In en, this message translates to:
  /// **'6-character code'**
  String get pairCodeHint;

  /// No description provided for @joinPair.
  ///
  /// In en, this message translates to:
  /// **'Join'**
  String get joinPair;

  /// No description provided for @pairCodeTtl.
  ///
  /// In en, this message translates to:
  /// **'Pairing code is valid for 30 minutes'**
  String get pairCodeTtl;

  /// No description provided for @filesHeader.
  ///
  /// In en, this message translates to:
  /// **'Files'**
  String get filesHeader;

  /// No description provided for @transferCorrupt.
  ///
  /// In en, this message translates to:
  /// **'“{name}” failed checksum. Please resend.'**
  String transferCorrupt(String name);

  /// No description provided for @transferPaused.
  ///
  /// In en, this message translates to:
  /// **'Network interrupted. “{name}” paused.'**
  String transferPaused(String name);

  /// No description provided for @deviceBrowser.
  ///
  /// In en, this message translates to:
  /// **'Browser'**
  String get deviceBrowser;

  /// No description provided for @purgeTitle.
  ///
  /// In en, this message translates to:
  /// **'Permanently delete “{title}”?'**
  String purgeTitle(String title);

  /// No description provided for @purgeBody.
  ///
  /// In en, this message translates to:
  /// **'Permanently deletes this source, {items} linked docs, {versions} history versions, and {checks} check logs—including linked inbox/trash docs, notes, and state.'**
  String purgeBody(int items, int versions, int checks);

  /// No description provided for @purgeRemovedRules.
  ///
  /// In en, this message translates to:
  /// **'Also removes {count} rules that only reference these docs.'**
  String purgeRemovedRules(int count);

  /// No description provided for @purgePausedRules.
  ///
  /// In en, this message translates to:
  /// **'Also pauses {count} rules that include these docs and requires recapture; other docs stay.'**
  String purgePausedRules(int count);

  /// No description provided for @purgePreviewInvalidate.
  ///
  /// In en, this message translates to:
  /// **'Unfinished capture previews for this account will expire and need recapture. Other saved docs stay. Offline extension caches clear on reconnect.'**
  String get purgePreviewInvalidate;

  /// No description provided for @purgeIrreversible.
  ///
  /// In en, this message translates to:
  /// **'This cannot be undone. You can capture the same page and query again later as new docs.'**
  String get purgeIrreversible;

  /// No description provided for @purgeConfirmCheck.
  ///
  /// In en, this message translates to:
  /// **'I confirm permanent deletion of these docs and history'**
  String get purgeConfirmCheck;

  /// No description provided for @sourcePurgedOk.
  ///
  /// In en, this message translates to:
  /// **'Source, linked docs, and history permanently deleted. Capture again to save.'**
  String get sourcePurgedOk;

  /// No description provided for @sourcePurgedPartial.
  ///
  /// In en, this message translates to:
  /// **'Server deleted permanently; local cache cleanup pending retry: {error}'**
  String sourcePurgedPartial(String error);

  /// No description provided for @accountChangedConfirm.
  ///
  /// In en, this message translates to:
  /// **'Desk account changed. Please confirm again.'**
  String get accountChangedConfirm;
}

class _AppLocalizationsDelegate
    extends LocalizationsDelegate<AppLocalizations> {
  const _AppLocalizationsDelegate();

  @override
  Future<AppLocalizations> load(Locale locale) {
    return SynchronousFuture<AppLocalizations>(lookupAppLocalizations(locale));
  }

  @override
  bool isSupported(Locale locale) =>
      <String>['en', 'zh'].contains(locale.languageCode);

  @override
  bool shouldReload(_AppLocalizationsDelegate old) => false;
}

AppLocalizations lookupAppLocalizations(Locale locale) {
  // Lookup logic when language+country codes are specified.
  switch (locale.languageCode) {
    case 'zh':
      {
        switch (locale.countryCode) {
          case 'TW':
            return AppLocalizationsZhTw();
        }
        break;
      }
  }

  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'en':
      return AppLocalizationsEn();
    case 'zh':
      return AppLocalizationsZh();
  }

  throw FlutterError(
    'AppLocalizations.delegate failed to load unsupported locale "$locale". This is likely '
    'an issue with the localizations generation tool. Please file an issue '
    'on GitHub with a reproducible sample app and the gen-l10n configuration '
    'that was used.',
  );
}
