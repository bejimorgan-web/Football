import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:football_streaming_app/main.dart';

void main() {
  testWidgets('app renders title', (WidgetTester tester) async {
    SharedPreferences.setMockInitialValues({});

    await tester.pumpWidget(const FootballStreamingApp());
    await tester.pump(const Duration(milliseconds: 100));

    expect(find.text('Football Streaming'), findsOneWidget);
  });
}
