import 'package:flutter/material.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

import 'src/api.dart';
import 'src/db.dart';
import 'src/state.dart';
import 'src/tokens.dart';
import 'src/ui/app.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final db = await LocalDb.open(
    databaseFactory,
    p.join(await getDatabasesPath(), 'nextcam_visitor.db'),
  );
  final state = AppState(api: ApiClient(SecureTokenStore()), db: db);
  await state.start();
  runApp(VisitorApp(state: state));
}
