import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

/// Entry availability is independent of authentication and of saved-item counts.
class CampusSourceEntry {
  final String id;
  final String name;
  final String url;
  final bool requiresLogin;
  final String scope;

  const CampusSourceEntry({
    required this.id,
    required this.name,
    required this.url,
    required this.requiresLogin,
    required this.scope,
  });
}

const campusSourceEntries = [
  CampusSourceEntry(
    id: 'student',
    name: 'College notices / student system',
    url: 'https://student-wmweb.must.edu.mo/',
    requiresLogin: true,
    scope: 'After sign-in, read home notices; timetable needs its own page.',
  ),
  CampusSourceEntry(
    id: 'fie',
    name: 'Faculty directory',
    url: 'https://fie.must.edu.mo/person/id-828.html?locale=zh_MO',
    requiresLogin: false,
    scope: 'Public staff directory; open a profile to read details.',
  ),
  CampusSourceEntry(
    id: 'moodle',
    name: 'Moodle courses & assignments',
    url: 'https://moodle.must.edu.mo/my/',
    requiresLogin: true,
    scope: 'After sign-in, open courses and read assignment requirements.',
  ),
];

class CampusSourceEntries extends StatelessWidget {
  const CampusSourceEntries({super.key});

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Text('Campus sources', style: Theme.of(context).textTheme.titleLarge),
      const Text(
        'Open the original page, capture matching content with the Chrome extension, preview, then save once. '
        'Previews stay in the local extension; saved items enter the desk. '
        'Gleaner and school accounts sign in separately.',
      ),
      for (final source in campusSourceEntries)
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  source.name,
                  style: const TextStyle(fontWeight: FontWeight.bold),
                ),
                Text(
                  source.requiresLogin
                      ? 'Requires original-site sign-in · this page does not check school session'
                      : 'Public page · no student sign-in',
                ),
                Text(source.scope),
                TextButton.icon(
                  onPressed: () => launchUrl(Uri.parse(source.url)),
                  icon: const Icon(Icons.open_in_new),
                  label: const Text('Open source page'),
                ),
              ],
            ),
          ),
        ),
    ],
  );
}
