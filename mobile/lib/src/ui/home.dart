import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../db.dart';
import '../format.dart';
import '../models.dart';
import '../state.dart';
import 'collection.dart';
import 'customer.dart';
import 'glass.dart';
import 'new_customer.dart';
import 'notifications.dart';
import 'order_detail.dart';
import 'report.dart';
import 'scan.dart';
import 'search.dart';
import 'widgets.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.state, this.now});
  final AppState state;

  /// Fixed clock for screenshots and tests.
  final DateTime? now;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _tab = 0;

  @override
  Widget build(BuildContext context) {
    final s = widget.state;
    final cat = s.catalog;
    final t = Theme.of(context);
    final name = cat?.visitorName ?? s.session?.fullName ?? '';
    return Scaffold(
      appBar: PreferredSize(
        preferredSize: const Size.fromHeight(80),
        child: SafeArea(
          bottom: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(14, 8, 14, 4),
            child: GlassPanel(
              radius: const BorderRadius.all(Radius.circular(22)),
              padding: const EdgeInsetsDirectional.fromSTEB(12, 8, 4, 8),
              child: Row(
                children: [
                  Container(
                    width: 40,
                    height: 40,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(14),
                      gradient: const LinearGradient(colors: [brand, brand2]),
                    ),
                    child: Text(
                      name.isEmpty ? '؟' : name.characters.first,
                      style: const TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w800,
                        fontSize: 17,
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          name,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontWeight: FontWeight.w800,
                            fontSize: 15,
                          ),
                        ),
                        if (cat != null)
                          Text(
                            '${cat.organization} · ${cat.branchName}',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              fontSize: 11,
                              color: t.colorScheme.onSurfaceVariant,
                            ),
                          ),
                      ],
                    ),
                  ),
                  InkWell(
                    borderRadius: BorderRadius.circular(99),
                    onTap: s.syncing ? null : s.syncNow,
                    child: SyncBadge(state: s),
                  ),
                  IconButton(
                    tooltip: 'اعلان‌ها',
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => NotificationsScreen(state: s),
                      ),
                    ),
                    icon: Badge(
                      isLabelVisible: s.unread > 0,
                      label: Text(faDigits(s.unread)),
                      child: const Icon(Icons.notifications_rounded),
                    ),
                  ),
                  PopupMenuButton<String>(
                    tooltip: 'بیشتر',
                    onSelected: (v) async {
                      if (v == 'logout') await _confirmLogout(context);
                      if (v == 'lite') await s.setLite(!s.lite);
                      if (v == 'gps') await s.setGps(!s.gps);
                      if (v == 'photos' && context.mounted) {
                        await _downloadPhotos(context);
                      }
                    },
                    itemBuilder: (_) => [
                      const PopupMenuItem(
                        value: 'photos',
                        child: Text('دریافت عکس‌ها برای کار بدون اینترنت'),
                      ),
                      CheckedPopupMenuItem(
                        value: 'gps',
                        checked: s.gps,
                        child: const Text('ثبت مکان بازدید و وصول'),
                      ),
                      CheckedPopupMenuItem(
                        value: 'lite',
                        checked: s.lite,
                        child: const Text('حالت سبک (بدون جلوه‌ی شیشه)'),
                      ),
                      const PopupMenuItem(value: 'logout', child: Text('خروج')),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
      body: cat == null
          ? EmptyView(
              icon: s.online
                  ? Icons.downloading_rounded
                  : Icons.cloud_off_rounded,
              title: s.online
                  ? 'در حال دریافت فهرست مشتریان و کالاها…'
                  : 'هنوز داده‌ای روی گوشی نیست',
              detail: s.online
                  ? null
                  : 'یک بار به اینترنت وصل شوید تا فهرست‌ها دریافت شود.',
            )
          : switch (_tab) {
              0 => _CustomersTab(
                state: s,
                catalog: cat,
                now: widget.now ?? DateTime.now(),
              ),
              1 => _OrdersTab(state: s, catalog: cat),
              2 => ReportTab(state: s, today: widget.now),
              _ => _OutboxTab(state: s, catalog: cat),
            },
      bottomNavigationBar: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 4, 14, 12),
          child: GlassPanel(
            child: NavigationBar(
              selectedIndex: _tab,
              onDestinationSelected: (i) => setState(() => _tab = i),
              destinations: [
                const NavigationDestination(
                  icon: Icon(Icons.people_alt_rounded),
                  label: 'مشتریان',
                ),
                const NavigationDestination(
                  icon: Icon(Icons.receipt_long_rounded),
                  label: 'سفارش‌ها',
                ),
                const NavigationDestination(
                  icon: Icon(Icons.insights_rounded),
                  label: 'گزارش من',
                ),
                NavigationDestination(
                  icon: Badge(
                    isLabelVisible: s.pending + s.failed > 0,
                    label: Text(faDigits(s.pending + s.failed)),
                    child: const Icon(Icons.outbox_rounded),
                  ),
                  label: 'صف',
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  /// Fetches every main photo in large size, with progress; stops when offline.
  Future<void> _downloadPhotos(BuildContext context) async {
    final s = widget.state;
    final progress = ValueNotifier<(int, int)>((0, 0));
    final messenger = ScaffoldMessenger.of(context);
    final nav = Navigator.of(context);
    unawaited(
      showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (_) => AlertDialog(
          title: const Text('دریافت عکس‌ها'),
          content: ValueListenableBuilder<(int, int)>(
            valueListenable: progress,
            builder: (_, p, _) => Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                LinearProgressIndicator(value: p.$2 == 0 ? null : p.$1 / p.$2),
                const SizedBox(height: 12),
                Text(
                  p.$2 == 0
                      ? 'در حال بررسی…'
                      : '${faDigits(p.$1)} از ${faDigits(p.$2)}',
                ),
              ],
            ),
          ),
        ),
      ),
    );
    var have = 0;
    try {
      have = await s.downloadPhotos((d, t) => progress.value = (d, t));
    } on ApiException catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      nav.pop();
    }
    final total = s.catalog?.items.where((i) => i.imageIds.isNotEmpty).length;
    messenger.showSnackBar(
      SnackBar(
        content: Text(
          s.online || have == total
              ? 'عکس ${faDigits(have)} کالا روی گوشی است'
              : 'اینترنت قطع شد؛ عکس ${faDigits(have)} کالا روی گوشی است',
        ),
      ),
    );
  }

  Future<void> _confirmLogout(BuildContext context) async {
    final s = widget.state;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('خروج از حساب'),
        content: Text(
          s.pending > 0
              ? '${faDigits(s.pending)} مورد هنوز ارسال نشده است. روی گوشی می‌ماند و پس از ورود دوباره‌ی شما ارسال می‌شود.'
              : 'از حساب خارج می‌شوید.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(c, false),
            child: const Text('انصراف'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(c, true),
            child: const Text('خروج'),
          ),
        ],
      ),
    );
    if (ok == true) await s.logout();
  }
}

class _CustomersTab extends StatefulWidget {
  const _CustomersTab({
    required this.state,
    required this.catalog,
    required this.now,
  });
  final AppState state;
  final Catalog catalog;
  final DateTime now;

  @override
  State<_CustomersTab> createState() => _CustomersTabState();
}

class _CustomersTabState extends State<_CustomersTab> {
  bool _today = true;

  @override
  Widget build(BuildContext context) {
    final day = iranWeekday(widget.now);
    final all = widget.catalog.customers;
    final list = all.where((c) {
      if (_today && c.visitWeekday != null && c.visitWeekday != day) {
        return false;
      }
      return true;
    }).toList();
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
          child: SearchBarButton(
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => SearchScreen(state: widget.state),
              ),
            ),
          ),
        ),
        _TargetCard(state: widget.state, today: widget.now),
        _QuickActions(state: widget.state, today: list),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 6),
          child: SegmentedButton<bool>(
            segments: [
              ButtonSegment(
                value: true,
                label: Text('مسیر امروز (${weekdayNames[day]})'),
              ),
              ButtonSegment(
                value: false,
                label: Text('همه (${faDigits(all.length)})'),
              ),
            ],
            selected: {_today},
            onSelectionChanged: (v) => setState(() => _today = v.first),
          ),
        ),
        Expanded(
          child: list.isEmpty
              ? const EmptyView(
                  icon: Icons.person_search_rounded,
                  title: 'مشتری‌ای در این فهرست نیست',
                )
              : ListView.separated(
                  padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
                  itemCount: list.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 8),
                  itemBuilder: (context, i) => _CustomerCard(
                    customer: list[i],
                    currency: widget.catalog.currency,
                    onTap: () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => CustomerScreen(
                          state: widget.state,
                          customer: list[i],
                        ),
                      ),
                    ),
                  ),
                ),
        ),
      ],
    );
  }
}

class _CustomerCard extends StatelessWidget {
  const _CustomerCard({
    required this.customer,
    required this.currency,
    required this.onTap,
  });
  final Customer customer;
  final String currency;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = customer;
    final outline = Theme.of(context).colorScheme.outline;
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(
            children: [
              Container(
                width: 42,
                height: 42,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.primaryContainer,
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Text(
                  c.name.characters.first,
                  style: TextStyle(
                    fontWeight: FontWeight.w800,
                    color: Theme.of(context).colorScheme.primary,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      c.name,
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      [
                        if (c.address != null) c.address!,
                        if (c.visitWeekday != null)
                          'روز بازدید: ${weekdayNames[c.visitWeekday!]}',
                      ].join(' · '),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: 12, color: outline),
                    ),
                  ],
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text('مانده', style: TextStyle(fontSize: 11, color: outline)),
                  Text(
                    money(c.balance, currency),
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _OrdersTab extends StatelessWidget {
  const _OrdersTab({required this.state, required this.catalog});
  final AppState state;
  final Catalog catalog;

  @override
  Widget build(BuildContext context) {
    final serverIds = state.orders.map((o) => o['id']).toSet();
    final local = state.outbox
        .where(
          (e) =>
              e.kind == 'order' &&
              e.status != 'sent' &&
              !serverIds.contains(e.id),
        )
        .toList();
    if (state.orders.isEmpty && local.isEmpty) {
      return const EmptyView(
        icon: Icons.receipt_long_rounded,
        title: 'هنوز سفارشی ثبت نشده است',
      );
    }
    return RefreshIndicator(
      onRefresh: state.syncNow,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          for (final e in local) ...[
            _OrderTile(
              title:
                  catalog.customer(e.payload['customer_id'] as String)?.name ??
                  '',
              subtitle:
                  '${jalaliDateTime(e.createdAt)} · ${faDigits((e.payload['lines'] as List).length)} قلم',
              amount: null,
              status: e.status,
              currency: catalog.currency,
            ),
            const SizedBox(height: 8),
          ],
          for (final o in state.orders) ...[
            _OrderTile(
              title: o['customer_name'] as String,
              subtitle:
                  'سفارش ${faDigits(o['number'] ?? '')} · ${jalaliDateTime(DateTime.parse(o['ordered_at'] as String))}'
                  '${o['invoice_number'] != null ? ' · فاکتور ${faDigits(o['invoice_number'])}' : ''}',
              amount: dec(o['grand_total'] as String),
              status: o['status'] as String,
              currency: catalog.currency,
              note: o['status'] == 'rejected'
                  ? o['decision_note'] as String?
                  : null,
              onCancel: o['status'] == 'submitted'
                  ? () => _cancel(context, o['id'] as String)
                  : null,
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => OrderDetailScreen(state: state, order: o),
                ),
              ),
            ),
            const SizedBox(height: 8),
          ],
        ],
      ),
    );
  }

  Future<void> _cancel(BuildContext context, String id) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      await state.cancelOrder(id);
      messenger.showSnackBar(const SnackBar(content: Text('سفارش لغو شد')));
    } catch (_) {
      messenger.showSnackBar(
        const SnackBar(
          content: Text('لغو سفارش فقط با اتصال به سرور ممکن است'),
        ),
      );
    }
  }
}

class _OrderTile extends StatelessWidget {
  const _OrderTile({
    required this.title,
    required this.subtitle,
    required this.amount,
    required this.status,
    required this.currency,
    this.note,
    this.onCancel,
    this.onTap,
  });
  final VoidCallback? onTap;
  final String title;
  final String subtitle;
  final dynamic amount;
  final String status;
  final String currency;
  final String? note;
  final VoidCallback? onCancel;

  @override
  Widget build(BuildContext context) {
    final outline = Theme.of(context).colorScheme.outline;
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      title,
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                  ),
                  StatusChip(status),
                ],
              ),
              const SizedBox(height: 4),
              Text(subtitle, style: TextStyle(fontSize: 12, color: outline)),
              if (amount != null) ...[
                const SizedBox(height: 6),
                Text(
                  money(amount, currency, unit: true),
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
              ],
              if (note != null) ...[
                const SizedBox(height: 4),
                Text('علت: $note', style: const TextStyle(fontSize: 12)),
              ],
              if (onCancel != null)
                Align(
                  alignment: AlignmentDirectional.centerEnd,
                  child: TextButton.icon(
                    onPressed: onCancel,
                    icon: const Icon(Icons.close_rounded, size: 18),
                    label: const Text('لغو سفارش'),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _OutboxTab extends StatelessWidget {
  const _OutboxTab({required this.state, required this.catalog});
  final AppState state;
  final Catalog catalog;

  @override
  Widget build(BuildContext context) {
    final items = state.outbox.where((e) => e.status != 'sent').toList();
    final synced = state.syncedAt;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              children: [
                LabelValue('در صف ارسال', faDigits(state.pending)),
                LabelValue('ارسال نشد (نیازمند بررسی)', faDigits(state.failed)),
                LabelValue(
                  'آخرین هماهنگی با سرور',
                  synced == null ? '—' : jalaliDateTime(synced),
                ),
                if (state.syncError != null)
                  LabelValue('پیام سرور', state.syncError!),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),
        if (items.isEmpty)
          const EmptyView(
            icon: Icons.cloud_done_rounded,
            title: 'همه‌چیز ارسال شده است',
            detail: 'سفارش‌ها و بازدیدهایی که بدون اینترنت ثبت کنید این‌جا می‌مانند تا ارسال شوند.',
          )
        else
          for (final e in items) ...[
            _OutboxTile(state: state, catalog: catalog, entry: e),
            const SizedBox(height: 8),
          ],
      ],
    );
  }
}

class _OutboxTile extends StatelessWidget {
  const _OutboxTile({
    required this.state,
    required this.catalog,
    required this.entry,
  });
  final AppState state;
  final Catalog catalog;
  final OutboxEntry entry;

  @override
  Widget build(BuildContext context) {
    final e = entry;
    final customer =
        catalog.customer(e.payload['customer_id'] as String? ?? '')?.name ?? '';
    final what = switch (e.kind) {
      'order' => 'سفارش ${faDigits((e.payload['lines'] as List).length)} قلمی',
      'collection' =>
        'وصول ${collectionMethodLabel[e.payload['method']] ?? ''} ${money(dec(e.payload['amount'] as String), catalog.currency)}',
      'customer_request' => 'مشتری جدید: ${e.payload['name']}',
      _ => 'بازدید: ${visitOutcomeLabel[e.payload['outcome']] ?? ''}',
    };
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    customer.isEmpty ? what : '$what — $customer',
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
                StatusChip(e.status),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              jalaliDateTime(e.createdAt),
              style: TextStyle(
                fontSize: 12,
                color: Theme.of(context).colorScheme.outline,
              ),
            ),
            if (e.error != null) ...[const SizedBox(height: 6), Text(e.error!)],
            if (e.status == 'failed')
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: () => state.discard(e.id),
                    child: const Text('حذف از صف'),
                  ),
                  FilledButton.tonal(
                    onPressed: () => state.retry(e.id),
                    child: const Text('ارسال دوباره'),
                  ),
                ],
              ),
          ],
        ),
      ),
    );
  }
}

/// This month's target and progress (the invoiced amount), from the last report the
/// phone fetched; hidden when the manager set none.
class _TargetCard extends StatefulWidget {
  const _TargetCard({required this.state, required this.today});
  final AppState state;
  final DateTime today;

  @override
  State<_TargetCard> createState() => _TargetCardState();
}

class _TargetCardState extends State<_TargetCard> {
  late final Future<(Map<String, dynamic>?, bool)> _load = widget.state.report(
    'month',
  );

  @override
  Widget build(BuildContext context) {
    return FutureBuilder(
      future: _load,
      builder: (context, snap) {
        final r = snap.data?.$1;
        if (r == null || r['target'] == null) return const SizedBox(height: 6);
        final target = dec(r['target'] as String);
        final done = dec(r['target_progress'] as String? ?? '0');
        final frac = target == dec('0') ? 0.0 : (done / target).toDouble();
        final (jy, jm, jd) = toJalali(tehran(widget.today));
        final left = jalaliMonthDays(jy, jm) - jd;
        final cur = widget.state.catalog?.currency ?? 'IRT';
        final soft = Theme.of(context).colorScheme.onSurfaceVariant;
        return Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          'هدف فروش ${jalaliMonths[jm - 1]}',
                          style: const TextStyle(fontWeight: FontWeight.w800),
                        ),
                      ),
                      Text(
                        '${faDigits(left)} روز مانده',
                        style: TextStyle(fontSize: 11, color: soft),
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          '${money(done, cur)} از ${money(target, cur, unit: true)}',
                          style: TextStyle(fontSize: 12, color: soft),
                        ),
                      ),
                      Text(
                        '${faDigits((frac * 100).round())}٪',
                        style: TextStyle(
                          fontWeight: FontWeight.w800,
                          color: Theme.of(context).colorScheme.primary,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(6),
                    child: LinearProgressIndicator(
                      value: frac.clamp(0, 1),
                      minHeight: 8,
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}

class _QuickActions extends StatelessWidget {
  const _QuickActions({required this.state, required this.today});
  final AppState state;
  final List<Customer> today;

  Future<void> _route(BuildContext context) async {
    final located = today.where((c) => c.located).toList();
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheet) => located.isEmpty
          ? const SizedBox(
              height: 160,
              child: EmptyView(
                icon: Icons.location_off_rounded,
                title: 'مکان مشتریان امروز ثبت نشده',
                detail: 'در صفحه‌ی هر مشتری، کنار مغازه «ثبت مکان» را بزنید.',
              ),
            )
          : ListView(
              shrinkWrap: true,
              children: [
                for (final c in located)
                  ListTile(
                    leading: const Icon(Icons.storefront_rounded),
                    title: Text(c.name),
                    subtitle: c.address == null ? null : Text(c.address!),
                    trailing: const Icon(Icons.directions_rounded),
                    onTap: () => state.device.openMap(
                      c.latitude!.toDouble(),
                      c.longitude!.toDouble(),
                      c.name,
                    ),
                  ),
              ],
            ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = Theme.of(context).colorScheme.primary;
    Widget action(IconData icon, String label, VoidCallback onTap) => Expanded(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 3),
        child: Card(
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: onTap,
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 9),
              child: Column(
                children: [
                  Icon(icon, color: p, size: 22),
                  const SizedBox(height: 3),
                  Text(
                    label,
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                      color: p,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
    void open(Widget screen) =>
        Navigator.of(context).push(MaterialPageRoute(builder: (_) => screen));
    return Padding(
      padding: const EdgeInsets.fromLTRB(13, 8, 13, 4),
      child: Row(
        children: [
          action(
            Icons.payments_rounded,
            'وصول وجه',
            () => open(CollectionScreen(state: state)),
          ),
          action(
            Icons.person_add_alt_1_rounded,
            'مشتری جدید',
            () => open(NewCustomerScreen(state: state)),
          ),
          action(Icons.qr_code_scanner_rounded, 'اسکن کالا', () async {
            final code = await scanBarcode(context);
            if (code != null && context.mounted) {
              open(SearchScreen(state: state, initial: code));
            }
          }),
          action(Icons.route_rounded, 'مسیر امروز', () => _route(context)),
        ],
      ),
    );
  }
}
