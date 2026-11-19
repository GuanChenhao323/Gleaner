// ignore: unused_import
import 'package:intl/intl.dart' as intl;

import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class AppLocalizationsEn extends AppLocalizations {
  AppLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String get appTitle => '拾课 Gleaner';

  @override
  String get navDesk => 'Desk';

  @override
  String get navInbox => 'Inbox';

  @override
  String get navCourses => 'Courses';

  @override
  String get navSources => 'Sources';

  @override
  String get navSettings => 'Settings';

  @override
  String get navCompose => 'Compose';

  @override
  String get navTransfer => 'Transfer';

  @override
  String get navAccount => 'Account';

  @override
  String get navMore => 'More';

  @override
  String get actionView => 'View';

  @override
  String get actionClose => 'Close';

  @override
  String get actionSave => 'Save';

  @override
  String get actionCancel => 'Cancel';

  @override
  String get actionGotIt => 'Got it';

  @override
  String get actionSyncNow => 'Sync now';

  @override
  String get login => 'Sign in';

  @override
  String get loginOrRegister => 'Sign in or register';

  @override
  String get register => 'Create account';

  @override
  String get registerAndStart => 'Register and start';

  @override
  String get email => 'Email';

  @override
  String get password => 'Password';

  @override
  String get passwordMin8 => 'Password (at least 8 characters)';

  @override
  String get emailCode => 'Email code';

  @override
  String get getCode => 'Get code';

  @override
  String resendInSeconds(int seconds) {
    return '${seconds}s to resend';
  }

  @override
  String get nickname => 'Display name';

  @override
  String get grade => 'Year';

  @override
  String get major => 'Major';

  @override
  String get agreePrivacy => 'I have read the privacy notice';

  @override
  String get privacyAgreeDetail =>
      '拾课 Gleaner stores Moodle session cookies, not SSO passwords. School mailbox app passwords are encrypted with AES-GCM. Mail keeps only subject, sender, summary, and links. You can delete your account anytime.';

  @override
  String get serverAddress => 'Server URL';

  @override
  String get haveAccountSignIn => 'Already have an account? Sign in';

  @override
  String get noAccountRegister => 'No account yet? Register';

  @override
  String codeSent(String email) {
    return 'Code sent to $email. Valid for 10 minutes.';
  }

  @override
  String get guestDesk =>
      'Sign in to see today’s tasks and deadlines this week.';

  @override
  String get guestInbox =>
      'Sign in to see assignments, notices, and page updates.';

  @override
  String get guestCourses =>
      'Sign in to browse assignments and deadlines by course.';

  @override
  String get guestSources =>
      'Sign in to manage campus pages and Moodle sources.';

  @override
  String get guestSettings =>
      'Sign in to manage your profile and notification settings.';

  @override
  String get sectionNotifications => 'Notifications';

  @override
  String get sectionConnection => 'Connection';

  @override
  String get sectionAccount => 'Account';

  @override
  String get quietHours => 'Do not disturb';

  @override
  String get dailyDigest => 'Daily digest';

  @override
  String dailyDigestAt(String time) {
    return 'Every day at $time';
  }

  @override
  String get digestAlsoEmail => 'Also email the digest';

  @override
  String get personalRules => 'Personal rules';

  @override
  String get pushStatus => 'Push status';

  @override
  String get connected => 'Connected';

  @override
  String get connecting => 'Connecting…';

  @override
  String get disconnected => 'Disconnected';

  @override
  String get sync => 'Sync';

  @override
  String syncPending(int count) {
    return '$count pending';
  }

  @override
  String get syncUpToDate => 'Up to date';

  @override
  String get server => 'Server';

  @override
  String get privacy => 'Privacy';

  @override
  String get privacyBody =>
      'Moodle and similar sources keep login sessions only, not SSO passwords. School mailbox app passwords and sessions are encrypted with AES-GCM. Mail keeps only subject, sender, summary, and links. You can delete your account and all data anytime.';

  @override
  String get changePassword => 'Change password';

  @override
  String get signOut => 'Sign out';

  @override
  String get deleteAccount => 'Delete account';

  @override
  String get language => 'Language';

  @override
  String get languageEnglish => 'English';

  @override
  String get languageSimplified => '简体中文';

  @override
  String get languageTraditional => '繁體中文';

  @override
  String get inboxUnread => 'Unread';

  @override
  String get inboxStarred => 'Starred';

  @override
  String get inboxTodo => 'To-do';

  @override
  String get inboxEvent => 'Events';

  @override
  String get inboxNotice => 'Notices';

  @override
  String get inboxTrash => 'Trash';

  @override
  String get statusOpen => 'Open';

  @override
  String get statusDone => 'Done';

  @override
  String get statusActive => 'Active';

  @override
  String get statusArchived => 'Archived';

  @override
  String get statusUnread => 'Unread';

  @override
  String get statusRead => 'Read';

  @override
  String get statusAll => 'All';

  @override
  String get newLabel => 'New label';

  @override
  String get labels => 'Labels';

  @override
  String get pinSidebar => 'Pin sidebar';

  @override
  String get unpinSidebar => 'Unpin sidebar';

  @override
  String get saved => 'Saved';

  @override
  String get classmate => 'there';

  @override
  String get justNow => 'Just now';

  @override
  String get never => 'Never';

  @override
  String minutesAgo(int count) {
    return '$count min ago';
  }

  @override
  String hoursAgo(int count) {
    return '$count h ago';
  }

  @override
  String yesterdayAt(String time) {
    return 'Yesterday $time';
  }

  @override
  String get today => 'Today';

  @override
  String get tomorrow => 'Tomorrow';

  @override
  String get dayAfterTomorrow => 'In 2 days';

  @override
  String get yesterday => 'Yesterday';

  @override
  String overdueHours(int count) {
    return 'Overdue $count h';
  }

  @override
  String overdueDays(int count) {
    return 'Overdue $count d';
  }

  @override
  String remainingMinutes(int count) {
    return '$count min left';
  }

  @override
  String remainingHours(int count) {
    return '$count h left';
  }

  @override
  String remainingDaysHours(int days, int hours) {
    return '$days d $hours h left';
  }

  @override
  String remainingDays(int count) {
    return '$count d left';
  }

  @override
  String get kindAssignment => 'Assignment';

  @override
  String get kindEvent => 'Event';

  @override
  String get kindNotice => 'Notice';

  @override
  String get kindMail => 'Mail';

  @override
  String get kindClip => 'Clip';

  @override
  String get kindPage => 'Page';

  @override
  String get kindItem => 'Item';

  @override
  String get channelWeb => 'Website';

  @override
  String get channelMail => 'Mail';

  @override
  String get sourceOk => 'OK';

  @override
  String get sourceFailed => 'Check failed';

  @override
  String get sourceNeedLogin => 'Sign in again';

  @override
  String get sourceWaiting => 'Waiting for first check';

  @override
  String get greetingLateNight => 'Still up';

  @override
  String get greetingMorning => 'Good morning';

  @override
  String get greetingNoon => 'Good noon';

  @override
  String get greetingAfternoon => 'Good afternoon';

  @override
  String get greetingEvening => 'Good evening';

  @override
  String get priorityUrgent => 'Urgent';

  @override
  String get priorityNormal => 'Normal';

  @override
  String get priorityLow => 'Low';

  @override
  String get typeTodo => 'To-do';

  @override
  String get typeEvent => 'Event';

  @override
  String get typeNotice => 'Notice';

  @override
  String get markOpen => 'Mark open';

  @override
  String get markDone => 'Mark done';

  @override
  String get unarchive => 'Unarchive';

  @override
  String get archive => 'Archive';

  @override
  String get markUnread => 'Mark unread';

  @override
  String get markRead => 'Mark read';

  @override
  String get fieldTitle => 'Title';

  @override
  String get fieldSummary => 'Summary';

  @override
  String get fieldType => 'Type';

  @override
  String get fieldDeadline => 'Deadline';

  @override
  String get fieldStart => 'Start';

  @override
  String get fieldEnd => 'End';

  @override
  String get fieldLocation => 'Location';

  @override
  String get fieldRequirements => 'Requirements';

  @override
  String get emptyValue => '(empty)';

  @override
  String get done => 'Done';

  @override
  String get deskTodayFocus => 'Today';

  @override
  String get deskThisWeek => 'This week';

  @override
  String get deskNeedsAttention => 'Needs attention';

  @override
  String get deskCalendar => 'Calendar';

  @override
  String get deskHideCalendar => 'Hide calendar';

  @override
  String get deskDueIn7Days => 'Due in 7 days';

  @override
  String get deskSourceIssues => 'Source issues';

  @override
  String get deskShowMore => 'Show more';

  @override
  String get deskInboxLink => 'Inbox';

  @override
  String get filterAll => 'All';

  @override
  String get summary => 'Summary';

  @override
  String get requirements => 'Requirements';

  @override
  String get originalContent => 'Original';

  @override
  String get sourceMonitor => 'Source monitoring';

  @override
  String deadlineAt(String when) {
    return 'Due $when';
  }

  @override
  String get openSource => 'Open source';

  @override
  String get edit => 'Edit';

  @override
  String get notImportant => 'Not important';

  @override
  String get copyLink => 'Copy link';

  @override
  String get star => 'Star';

  @override
  String get unstar => 'Unstar';

  @override
  String get weekdayMon => 'Mon';

  @override
  String get weekdayTue => 'Tue';

  @override
  String get weekdayWed => 'Wed';

  @override
  String get weekdayThu => 'Thu';

  @override
  String get weekdayFri => 'Fri';

  @override
  String get weekdaySat => 'Sat';

  @override
  String get weekdaySun => 'Sun';

  @override
  String get generateQr => 'Generate QR code';

  @override
  String get orEnterCode => 'Or enter pairing code';

  @override
  String get codeHint => '6-digit code';

  @override
  String get join => 'Join';

  @override
  String get scanQr => 'Scan QR code';

  @override
  String get codeValid30m => 'Code valid for 30 minutes';

  @override
  String get paired => 'Paired';

  @override
  String get waitingPair => 'Waiting to pair…';

  @override
  String get sendFile => 'Send file';

  @override
  String get files => 'Files';

  @override
  String get noFilesYet => 'No files yet';

  @override
  String get send => 'Send';

  @override
  String get to => 'To';

  @override
  String get ccOptional => 'Cc (optional)';

  @override
  String get subject => 'Subject';

  @override
  String get bodyHint => 'Message';

  @override
  String get addAttachment => 'Attach';

  @override
  String get recentSent => 'Recently sent';

  @override
  String get noSubject => '(no subject)';

  @override
  String get pleaseFillRecipient => 'Enter a recipient';

  @override
  String get sent => 'Sent';

  @override
  String get duplicateSend => 'Already sent; not sent again';

  @override
  String sendFailed(String error) {
    return 'Send failed: $error';
  }

  @override
  String get lastCheckFailed => 'Last check failed';

  @override
  String get lastSuccessCheck => 'Last successful check';

  @override
  String get reason => 'Reason';

  @override
  String get failedAt => 'Failed';

  @override
  String get nextCheck => 'Next check';

  @override
  String get goHandle => 'Fix';

  @override
  String get fieldBody => 'Body';

  @override
  String operationFailed(String error) {
    return 'Failed: $error';
  }

  @override
  String get pluginCapture => 'Extension capture';

  @override
  String get alreadyStarted => 'Started';

  @override
  String get conflictBanner =>
      'Source content you edited also changed. Choose which version to keep.';

  @override
  String mineValue(String value) {
    return 'Mine: $value';
  }

  @override
  String sourceValue(String value) {
    return 'Source: $value';
  }

  @override
  String get keepMine => 'Keep mine';

  @override
  String get useSource => 'Use source';

  @override
  String get monitorUnsupported =>
      'Auto-check not supported; open the source to verify manually';

  @override
  String get monitorDisabled => 'Auto-check is off';

  @override
  String get monitorPending => 'On; waiting for first check';

  @override
  String get monitorUnchanged => 'Last check: no change';

  @override
  String get monitorChanged => 'Last check: changes found';

  @override
  String get monitorFailed => 'Last check failed';

  @override
  String get errAuthExpired => 'Login expired: sign in again in the browser';

  @override
  String get errForbidden => 'No permission to open this page';

  @override
  String get errNetwork => 'Network error';

  @override
  String get errNotFound => 'Item not found on the page';

  @override
  String get errParseFailed => 'Page structure changed; cannot parse yet';

  @override
  String get errUnsupported => 'This page no longer supports auto-check';

  @override
  String get lastSuccessNever => 'none yet';

  @override
  String lastSuccessCheckLine(String when) {
    return 'Last successful check: $when';
  }

  @override
  String reasonLine(String reason) {
    return 'Reason: $reason';
  }

  @override
  String failedAtLine(String when) {
    return 'Failed: $when';
  }

  @override
  String nextCheckLine(String when) {
    return 'Next check: $when (needs Chrome and local backend)';
  }

  @override
  String get restoreSourceValue => 'Restore source';

  @override
  String get willRestoreSource => 'Will restore source';

  @override
  String get notSet => 'Not set';

  @override
  String get choose => 'Choose';

  @override
  String get clear => 'Clear';

  @override
  String get editItem => 'Edit item';

  @override
  String get editItemHint =>
      'Edits only affect what you see. Source updates won’t overwrite them; you’ll be asked if the source also changes.';

  @override
  String get editsSaved => 'Changes saved';

  @override
  String oldValue(String value) {
    return 'Old: $value';
  }

  @override
  String newValue(String value) {
    return 'New: $value';
  }

  @override
  String get filterTodoTasks => 'To-dos';

  @override
  String get filterEvents => 'Events';

  @override
  String get filterNotices => 'Notices';

  @override
  String get todayShort => 'Today';

  @override
  String monthDay(int month, int day) {
    return '$month/$day';
  }

  @override
  String scorePoints(num score) {
    return '$score pts';
  }

  @override
  String get webMaterial => 'Web clip';

  @override
  String get sourceDeleted => 'Removed at source';

  @override
  String originalTitle(String title) {
    return 'Original title: $title';
  }

  @override
  String get sourceAndReliability => 'Source & reliability';

  @override
  String get unknownSource => 'Unknown source';

  @override
  String get lastSaved => 'Last saved';

  @override
  String get crossChannelMerge => 'Merged across channels';

  @override
  String sameItemMerged(String channels) {
    return 'Same item appeared in $channels; merged into one';
  }

  @override
  String get whyPushed => 'Why you got this';

  @override
  String changedToType(String type) {
    return 'Changed to $type';
  }

  @override
  String get goWorkbench => 'Open desk';

  @override
  String get changeTypeFailed => 'Couldn’t change type; try again';

  @override
  String get notImportantToast =>
      'Lowered this source’s weight; suggestions will adapt';

  @override
  String get copiedTitleLink => 'Title and link copied';

  @override
  String changeTypeCurrent(String type) {
    return 'Change type (now $type)';
  }

  @override
  String get completed => 'Completed';

  @override
  String get manuallyCorrected => '(manually corrected)';

  @override
  String get editHistory => 'Edit history';

  @override
  String versionsCount(int count) {
    return '$count versions';
  }

  @override
  String get firstSeen => 'First seen';

  @override
  String get contentUpdated => 'Content updated';

  @override
  String get noDeadlines => 'No deadlines';

  @override
  String get unreadStatus => 'Unread';

  @override
  String attachmentsCount(int count) {
    return '$count attachments';
  }

  @override
  String get deskEmptyToday => 'Nothing urgent today';

  @override
  String deskEmptyFilter(String filter) {
    return 'No $filter';
  }

  @override
  String get statusChanged => 'Changed';

  @override
  String get statusUrgent => 'Urgent';

  @override
  String sourceNeedLoginNamed(String name) {
    return '“$name” needs sign-in again';
  }

  @override
  String sourceCheckFailedNamed(String name) {
    return '“$name” check failed';
  }

  @override
  String andMoreItems(int count) {
    return '+$count more';
  }

  @override
  String get summaryLlmHint =>
      'Generated by model · guidance only; original text wins';

  @override
  String get summaryRuleHint =>
      'Rule extract · guidance only; original text wins';

  @override
  String get attachments => 'Attachments';

  @override
  String get sourceRawFields => 'Source fields';

  @override
  String get sfCourse => 'Course';

  @override
  String get sfSemester => 'Term';

  @override
  String get sfWeek => 'Week';

  @override
  String get sfWeekday => 'Weekday';

  @override
  String get sfPeriod => 'Period';

  @override
  String get sfDatetime => 'Original time';

  @override
  String get sfOffice => 'Office';

  @override
  String get sfDepartment => 'Department';

  @override
  String get sfRole => 'Role';

  @override
  String get sfPhone => 'Phone';

  @override
  String get sfEmail => 'Email';

  @override
  String get sfSubtype => 'Category';

  @override
  String get conditionSourceCheck => 'Conditional source check';

  @override
  String get viewSourceCheckSettings => 'View source & check settings';

  @override
  String get browserSourceCheck => 'Browser source check';

  @override
  String get snapshotOnlyNoBg =>
      'Snapshot only · background check not supported';

  @override
  String get myNotes => 'My notes (source updates won’t overwrite)';

  @override
  String get groupOverdue => 'Overdue';

  @override
  String get groupNextWeek => 'Next week';

  @override
  String get groupLater => 'Later';

  @override
  String get groupNoDeadline => 'No deadline';

  @override
  String get assignments => 'Assignments';

  @override
  String get noAssignmentsYet => 'No assignments yet';

  @override
  String doneCount(int count) {
    return '$count completed';
  }

  @override
  String get noNotices => 'No notices';

  @override
  String get statusPending => 'Open';

  @override
  String get courseNeedNetwork => 'Course info needs a network connection';

  @override
  String get courseNotFound => 'Course not found';

  @override
  String get backToCourses => 'Back to courses';

  @override
  String get markReadShort => 'Mark read';

  @override
  String get markUnreadShort => 'Mark unread';

  @override
  String get addTodo => 'Add to-do';

  @override
  String get removeTodo => 'Remove to-do';

  @override
  String get calMonth => 'Month';

  @override
  String get calTwoWeeks => '2 weeks';

  @override
  String get calWeek => 'Week';

  @override
  String get brandFallback => 'CR';

  @override
  String get bcNotExecuted => 'Awaiting first check';

  @override
  String get bcUnchanged => 'Check OK · no change';

  @override
  String get bcChanged => 'Source changed';

  @override
  String get bcNeedLogin => 'Sign in again on the school site';

  @override
  String get bcAccountMismatch =>
      'School account switched · old binding stopped';

  @override
  String get bcSelectionMissing => 'Original selection lost · recapture needed';

  @override
  String get bcViewMismatch => 'Term/week view invalid · recapture needed';

  @override
  String get bcRouteMismatch => 'Source route changed · recapture needed';

  @override
  String get bcRenderTimeout => 'Page load timed out';

  @override
  String get bcPermissionDenied => 'Browser source permission denied';

  @override
  String get bcUnsupported => 'Monitoring not supported';

  @override
  String get bcFailed => 'Check failed';

  @override
  String get rrRejected =>
      'Check result rejected · data kept, monitoring paused';

  @override
  String get rrPurged => 'Linked docs deleted · extract again from the page';

  @override
  String get rrStarting => 'Auto-monitor starting · waiting for first refresh';

  @override
  String get rrUserBusy => 'Monitor page is being edited · refresh deferred';

  @override
  String get rrTabMissing => 'Monitor tab closed · open the page and rebind';

  @override
  String get rrTabRebind =>
      'Browser session restarted · rebind the monitor tab';

  @override
  String get rrTabAmbiguous =>
      'Multiple same pages open · keep one monitor tab';

  @override
  String get rrSingleAccount => 'Another account bound on this site · paused';

  @override
  String get rrRestored => 'Source restored · check paused until retested';

  @override
  String get rrDocsRestored => 'Docs restored · source check still paused';

  @override
  String get rrDocsTrashed => 'Linked docs moved to trash · check paused';

  @override
  String get rrPrivateRequired =>
      'Login detected · recapture as a signed-in source';

  @override
  String get rrVerified => 'Reread verified · awaiting check';

  @override
  String get rrAccountUnknown =>
      'Cannot verify source account · keep manual capture';

  @override
  String get rrAccountMismatch => 'Source account mismatch · paused';

  @override
  String get rrNoMatch => 'No match this time · kept previous data';

  @override
  String get rrPreviewOnly => 'Incomplete content · data not overwritten';

  @override
  String get rrUnsupported => 'Background reread not supported';

  @override
  String get rrWorkerInterrupted => 'Browser task interrupted · retry';

  @override
  String get deadlineCalendar => 'Deadline calendar';

  @override
  String get rsExpired => 'Check timed out · waiting for browser retry';

  @override
  String get rsQueued => 'Queued · waiting to run';

  @override
  String get rsChecking => 'Checking in browser';

  @override
  String get rsWaitChrome => 'Waiting for local Chrome';

  @override
  String get rsLoginReuse => 'Reuse current Chrome session (confirmed)';

  @override
  String get rsLoginNone => 'No login required (declared)';

  @override
  String get rsLoginRequired => 'Login required';

  @override
  String get rsIdResidentGeneric =>
      'Dedicated monitor tab · single-account session';

  @override
  String get rsIdResidentSchool => 'School account · dedicated monitor tab';

  @override
  String get rsIdPublic => 'No login (user declared)';

  @override
  String get rsAccountUnchecked => 'account unchecked';

  @override
  String get rsIdSchoolChrome => 'School account · local Chrome';

  @override
  String get rsTitleTimeline => 'Moodle activity summary';

  @override
  String get rsTitleTeacher => 'Faculty profile';

  @override
  String get rsTitleWeb => 'Web clip';

  @override
  String get rsScopeTitle => 'Title and link titles';

  @override
  String get rsScopeTimeline => 'Loaded activities · full summary set';

  @override
  String get rsScopeBody => 'Body and lists · full match set';

  @override
  String get rsScopeOriginal => 'Original conditions and agreed view';

  @override
  String get rsWaitLocalChrome => 'Waiting for local Chrome';

  @override
  String get rsStartingCheck => 'Starting / checking';

  @override
  String get rsPeriodicPaused => 'Periodic monitoring paused';

  @override
  String get rsPartialPaused => 'Some rules paused';

  @override
  String get rsPeriodicOn => 'Periodic monitoring on';

  @override
  String get rsManualOnly => 'Manual check only';

  @override
  String get rsAwaitFirstRefresh => 'Waiting for first refresh';

  @override
  String get rsDedicatedMonitor => 'Dedicated monitor page';

  @override
  String labelCreated(String name) {
    return 'Created “$name”';
  }

  @override
  String labelDeleted(String name) {
    return 'Deleted “$name”';
  }

  @override
  String deleteLabelTitle(String name) {
    return 'Delete “$name”?';
  }

  @override
  String get deleteLabelBody =>
      'This label will be removed from items. Stars are unchanged.';

  @override
  String get actionDelete => 'Delete';

  @override
  String get searchInboxHint => 'Search title, course, or source';

  @override
  String get inboxEmptyFilter => 'No items for this filter';

  @override
  String get tagItem => 'Label this item';

  @override
  String get loadingLabels => 'Loading labels';

  @override
  String get labelsLoadFailed => 'Couldn’t load labels';

  @override
  String get retry => 'Retry';

  @override
  String get noLabelsYet => 'No labels yet. Create one first.';

  @override
  String get newLabelAction => 'New label';

  @override
  String get labelNameHint => 'e.g. Starred, Homework, Club';

  @override
  String get color => 'Color';

  @override
  String get create => 'Create';

  @override
  String get movedToTrash => 'Moved to trash. Content and history kept.';

  @override
  String get restoredItem => 'Restored. Source checks stay paused.';

  @override
  String get undo => 'Undo';

  @override
  String get accountChanged => 'Desk account changed';

  @override
  String restoreIncomplete(String error) {
    return 'Restore incomplete: $error';
  }

  @override
  String actionUnconfirmed(String error) {
    return 'Action not confirmed: $error';
  }

  @override
  String get restoreToInbox => 'Restore to inbox';

  @override
  String get moveToTrash => 'Move to trash';

  @override
  String get cannotOpenItem => 'Can’t open this item';

  @override
  String get itemNotFound =>
      'Item missing or not yours. Use the same 拾课 Gleaner account in desk and extension.';

  @override
  String get loginExpired => 'Session expired. Sign in again on the desk.';

  @override
  String get detailLoadFailed =>
      'Couldn’t load details. Check the backend and retry.';

  @override
  String currentDeskAccount(String email) {
    return 'Current desk account: $email';
  }

  @override
  String get notSignedIn => 'Not signed in';

  @override
  String get backToSources => 'Back to sources';

  @override
  String get notProvided => 'Not provided';

  @override
  String get sourceDeadline => 'Source deadline';

  @override
  String get submitRequirements => 'Submission requirements';

  @override
  String get sourceFields => 'Source fields';

  @override
  String beforeChange(String value) {
    return 'Before:\n$value';
  }

  @override
  String afterChange(String value) {
    return 'After:\n$value';
  }

  @override
  String timelineMaterial(int count) {
    return 'Activity summary · $count activities';
  }

  @override
  String webSnapshot(int count) {
    return 'Web snapshot · $count fragments';
  }

  @override
  String activityN(int n, String title) {
    return 'Activity $n: $title';
  }

  @override
  String fragmentN(int n, String title) {
    return 'Fragment $n: $title';
  }

  @override
  String get openActivity => 'Open activity';

  @override
  String courseField(String value) {
    return 'Course: $value';
  }

  @override
  String wcCond(String value) {
    return 'Query: $value';
  }

  @override
  String get wcIdentitySchool =>
      'Source identity: school account · local Chrome';

  @override
  String get wcScopeTimeline => 'Scope: currently loaded Timeline activities';

  @override
  String get wcMatchTitle => 'Match: titles and link titles';

  @override
  String get wcMatchBody => 'Match: body and lists';

  @override
  String wcAlias(String value) {
    return 'Source alias: $value';
  }

  @override
  String get wcLoginNone => 'Site login: not required (user declared)';

  @override
  String get wcLoginRequired => 'Site login: required';

  @override
  String wcAccount(String value) {
    return 'Source account: $value';
  }

  @override
  String get wcAccountUnchecked => 'unchecked';

  @override
  String get wcPrivateOnly => 'Visibility: only me';

  @override
  String get wcTimelineHint =>
      'Activity reminder summary only; detail bodies were not read. Dates/times stay as original text; missing values are not guessed.';

  @override
  String get wcLinkedHint =>
      'Matched fragments in the agreed view only—not a full article or email. Linked to a source; check method and status under Sources.';

  @override
  String get wcUnlinkedHint =>
      'Currently loaded content only—not a full article or email. Alias is user-declared; source checks are off.';

  @override
  String get wcUpdateOnChange =>
      'When a check succeeds and content changes, the same item’s source version updates; personal notes and status stay.';

  @override
  String get wcUpdateOnRecapture =>
      'Re-extract and save with the same source tag, URL, query, and scope to update this item’s version.';

  @override
  String wcDateText(String value) {
    return 'Date text: $value';
  }

  @override
  String wcTimeText(String value) {
    return 'Time text: $value';
  }

  @override
  String wcDomEvidence(String value) {
    return 'DOM evidence: $value';
  }

  @override
  String get aliasMissing => 'not provided';

  @override
  String get changeNoteSep => '; ';

  @override
  String get changeNameSep => ', ';

  @override
  String changeDays(int count) {
    return '$count d';
  }

  @override
  String changeHours(int count) {
    return '$count h';
  }

  @override
  String changeDeadlineAdvanced(String span, String from, String to) {
    return 'Deadline moved earlier by $span ($from → $to)';
  }

  @override
  String changeDeadlinePostponed(String span, String from, String to) {
    return 'Deadline postponed by $span ($from → $to)';
  }

  @override
  String changeDeadlineAdded(String when) {
    return 'Deadline added $when';
  }

  @override
  String get changeDeadlineRemoved => 'Deadline removed';

  @override
  String changeAttachmentReplaced(String names) {
    return 'Attachments replaced: $names';
  }

  @override
  String changeAttachmentAdded(String names) {
    return 'Attachments added: $names';
  }

  @override
  String changeAttachmentRemoved(String names) {
    return 'Attachments removed: $names';
  }

  @override
  String get changeAttachmentUpdated => 'Attachment content updated';

  @override
  String get changeRequirements => 'Submission requirements changed';

  @override
  String get changeEventTime => 'Event time changed';

  @override
  String get changeLocation => 'Location changed';

  @override
  String get changeType => 'Type changed';

  @override
  String get changeTitle => 'Title changed';

  @override
  String get changeWording => 'Wording updated';

  @override
  String get sourceSessionExpired =>
      'Session expired. Sign in again under Sources.';

  @override
  String get eventReminder => 'Deadline reminder';

  @override
  String get eventImportantChange => 'Important change';

  @override
  String get eventNewItem => 'New item';

  @override
  String get digestTitle => 'Daily digest';

  @override
  String digestBody(int newCount, int upcoming) {
    return 'Past 24 hours: $newCount new items, $upcoming due soon';
  }

  @override
  String get reasonBlocked => 'Matched a blocked word';

  @override
  String reasonKeyword(String words) {
    return 'Keywords: $words';
  }

  @override
  String get reasonDue24h => 'Due within 24 hours';

  @override
  String get reasonDue7d => 'Due within 7 days';

  @override
  String get reasonYourCourse => 'Your course';

  @override
  String get reasonCourseItem => 'Course item';

  @override
  String get reasonGradeMajorMatch => 'Matches your year/major';

  @override
  String get reasonOtherAudience => 'For another year or major';

  @override
  String get reasonImportantChange => 'Important change';

  @override
  String get errMoodleNeedLogin => 'Not signed into this Moodle source yet';

  @override
  String get courseOpenCount => 'Open';

  @override
  String get noCoursesYet => 'No courses yet';

  @override
  String get noCoursesHint =>
      'Add a Moodle source to get a home page per course. Add the Faculty directory template for office and email.';

  @override
  String get noCourseTodos => 'Nothing open';

  @override
  String get addFacultySourceHint =>
      'Add a Faculty directory source to show teacher contacts';

  @override
  String get captureFromWeb => 'Capture from web';

  @override
  String get refreshSourceListTooltip =>
      'Refresh list status (does not open source pages)';

  @override
  String get cannotReadSources => 'Could not read sources';

  @override
  String get savedPages => 'Saved pages';

  @override
  String get periodicRules => 'Periodic rules';

  @override
  String get needsAttention => 'Needs attention';

  @override
  String get changesFound => 'Changes found';

  @override
  String get mySources => 'My sources';

  @override
  String get noReadingSources =>
      'No sources with saved conditions yet. Extract, preview, and save from the original page with the extension.';

  @override
  String get monitorTabHint =>
      'Keep the dedicated monitoring tab open; you can close the desk page. Keep Chrome, the extension, and the local service running—checks may be delayed.';

  @override
  String deletedSourcesTitle(int count) {
    return 'Deleted sources ($count)';
  }

  @override
  String get deletedSourcesSubtitle =>
      'Restored sources stay paused; permanent delete clears linked docs and history.';

  @override
  String deletedSourcesUnavailable(String error) {
    return 'Deleted sources unavailable: $error';
  }

  @override
  String get legacyDemoTitle => 'Legacy data & demo subscriptions';

  @override
  String get legacyDemoSubtitle =>
      'Existing data is kept; if conditions are missing, open the original page and capture again.';

  @override
  String get chromeConnectedHint =>
      'Local Chrome connected recently · original-site sign-in is checked per source';

  @override
  String get chromeDisconnectedHint =>
      'No recent executor connection · last successful results kept';

  @override
  String get checkQueued => 'Check queued; status updates after confirmation.';

  @override
  String get periodicResumed => 'Periodic checks resumed.';

  @override
  String get periodicPaused =>
      'Periodic checks paused; manual checks still work.';

  @override
  String get pageCheckQueued =>
      'Full-page check queued; rules on the same page share the refresh.';

  @override
  String get pagePlanUpdated => 'Full-page monitoring plan updated.';

  @override
  String get sourceDeletedKeep => 'Source deleted; docs and history kept.';

  @override
  String get sourceDeletedTrash =>
      'Source deleted; linked docs moved to trash.';

  @override
  String get deleteSourceTitle => 'Delete this source?';

  @override
  String get deleteSourceBody =>
      'Stops manual and periodic checks. Saved docs, notes, and history stay by default. Restore from Deleted sources; old jobs won’t auto-resume.';

  @override
  String get deleteSourceAlsoTrash => 'Also move linked docs to personal trash';

  @override
  String get deleteSourceAlsoTrashHint =>
      'Also hides them in other sources that reference them; restore from Inbox trash.';

  @override
  String get deleteSourceAction => 'Delete source';

  @override
  String get restoreSourceAction => 'Restore source';

  @override
  String get purgeForever => 'Delete permanently';

  @override
  String get checkStoppedKept =>
      'Checks stopped · docs and history kept as chosen';

  @override
  String get sourceRestoredPaused =>
      'Source restored and paused; retest re-read.';

  @override
  String get manageLegacySources => 'Manage legacy templates / demo sources';

  @override
  String get legacyCaptureSubtitle =>
      'Legacy capture · not auto-migrated to condition monitoring';

  @override
  String legacyCapturesFailed(String error) {
    return 'Could not read legacy data: $error';
  }

  @override
  String statusRefreshFailed(String error) {
    return 'Status refresh failed: $error';
  }

  @override
  String get profileTitle => 'Profile';

  @override
  String get coursesCommaHint => 'My courses (comma-separated)';

  @override
  String get coursesHintSample => 'Network Programming, Operating Systems';

  @override
  String get gradeHintSample => 'Class of 2024';

  @override
  String get majorHintSample => 'Computer Science';

  @override
  String get profileMatchHint =>
      'Year, major, and courses help decide if a notice is relevant to you.';

  @override
  String get quietStartHelp => 'Do-not-disturb start';

  @override
  String get quietEndHelp => 'Do-not-disturb end';

  @override
  String get digestTimeHelp => 'Daily digest time';

  @override
  String get currentPassword => 'Current password';

  @override
  String get newPasswordMin8 => 'New password (at least 8 characters)';

  @override
  String get passwordChangedToast =>
      'Password changed. Other devices need to sign in again.';

  @override
  String get confirmChangePassword => 'Update password';

  @override
  String get deleteAccountTitle => 'Delete account?';

  @override
  String get deleteAccountBody =>
      'This permanently deletes your account, subscriptions, sessions, personal state, and sent mail. Enter your password to confirm.';

  @override
  String get deleteForever => 'Delete permanently';

  @override
  String get rulesSavedToast =>
      'Rules saved. They apply to new items going forward.';

  @override
  String get priorityFormula =>
      'Priority = 100 × (0.30 source weight + 0.25 keywords + 0.25 deadline proximity + 0.20 match)';

  @override
  String get priorityBands =>
      '≥ 80 urgent (push) · 40–79 normal · < 40 feed & digest only';

  @override
  String get ruleKeyword => 'Keywords';

  @override
  String get ruleSenderWhitelist => 'Sender allowlist';

  @override
  String get ruleKeywordHint => 'e.g. scholarship, internship';

  @override
  String get ruleBlock => 'Block';

  @override
  String get actionAdd => 'Add';

  @override
  String get noCustomRules => 'No custom rules yet';

  @override
  String get defaultKeywordsHint =>
      'Default keywords: deadline, exam, reschedule, cancel.';

  @override
  String get teachersHeader => 'Faculty';

  @override
  String get orEnterPairCode => 'Or enter a pairing code';

  @override
  String get pairCodeHint => '6-character code';

  @override
  String get joinPair => 'Join';

  @override
  String get pairCodeTtl => 'Pairing code is valid for 30 minutes';

  @override
  String get filesHeader => 'Files';

  @override
  String transferCorrupt(String name) {
    return '“$name” failed checksum. Please resend.';
  }

  @override
  String transferPaused(String name) {
    return 'Network interrupted. “$name” paused.';
  }

  @override
  String get deviceBrowser => 'Browser';

  @override
  String purgeTitle(String title) {
    return 'Permanently delete “$title”?';
  }

  @override
  String purgeBody(int items, int versions, int checks) {
    return 'Permanently deletes this source, $items linked docs, $versions history versions, and $checks check logs—including linked inbox/trash docs, notes, and state.';
  }

  @override
  String purgeRemovedRules(int count) {
    return 'Also removes $count rules that only reference these docs.';
  }

  @override
  String purgePausedRules(int count) {
    return 'Also pauses $count rules that include these docs and requires recapture; other docs stay.';
  }

  @override
  String get purgePreviewInvalidate =>
      'Unfinished capture previews for this account will expire and need recapture. Other saved docs stay. Offline extension caches clear on reconnect.';

  @override
  String get purgeIrreversible =>
      'This cannot be undone. You can capture the same page and query again later as new docs.';

  @override
  String get purgeConfirmCheck =>
      'I confirm permanent deletion of these docs and history';

  @override
  String get sourcePurgedOk =>
      'Source, linked docs, and history permanently deleted. Capture again to save.';

  @override
  String sourcePurgedPartial(String error) {
    return 'Server deleted permanently; local cache cleanup pending retry: $error';
  }

  @override
  String get accountChangedConfirm =>
      'Desk account changed. Please confirm again.';
}
