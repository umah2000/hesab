import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../db.dart';
import '../format.dart';
import '../models.dart';
import '../state.dart';
import 'customer.dart';
import 'glass.dart';
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
                  SyncBadge(state: s),
                  IconButton(
                    tooltip: 'ارسال و به‌روزرسانی',
                    onPressed: s.syncing ? null : s.syncNow,
                    icon: const Icon(Icons.sync_rounded),
                  ),
                  PopupMenuButton<String>(
                    tooltip: 'بیشتر',
                    onSelected: (v) async {
                      if (v == 'logout') await _confirmLogout(context);
                      if (v == 'lite') await s.setLite(!s.lite);
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
                NavigationDestination(
                  icon: Badge(
                    isLabelVisible: s.pending + s.failed > 0,
                    label: Text(faDigits(s.pending + s.failed)),
                    child: const Icon(Icons.outbox_rounded),
                  ),
                  label: 'صف ارسال',
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
  String _q = '';

  @override
  Widget build(BuildContext context) {
    final day = iranWeekday(widget.now);
    final all = widget.catalog.customers;
    final list = all.where((c) {
      if (_today && c.visitWeekday != null && c.visitWeekday != day) {
        return false;
      }
      final q = _q.trim();
      return q.isEmpty ||
          c.name.contains(q) ||
          c.code.toLowerCase().contains(q.toLowerCase());
    }).toList();
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
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
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
          child: TextField(
            onChanged: (v) => setState(() => _q = v),
            decoration: const InputDecoration(
              hintText: 'جست‌وجوی مشتری',
              prefixIcon: Icon(Icons.search_rounded),
              isDense: true,
            ),
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
  });
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
        catalog.customer(e.payload['customer_id'] as String)?.name ?? '';
    final what = e.kind == 'order'
        ? 'سفارش ${faDigits((e.payload['lines'] as List).length)} قلمی'
        : 'بازدید: ${visitOutcomeLabel[e.payload['outcome']] ?? ''}';
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
                    '$what — $customer',
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
