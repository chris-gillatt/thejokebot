const DashboardHistory = (() => {
  const DAY = 24 * 60 * 60 * 1000;
  const dateString = (value) => new Date(value).toISOString().slice(0, 10);

  function utcDate(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error("Enter a valid UTC date.");
    const timestamp = Date.parse(`${value}T00:00:00Z`);
    if (!Number.isFinite(timestamp) || dateString(timestamp) !== value) {
      throw new Error("Enter a valid UTC date.");
    }
    return timestamp;
  }

  function range(selection, generatedAt, custom = {}, earliest = null) {
    const end = utcDate(generatedAt.slice(0, 10));
    let start;
    let stop = end;
    if (selection === "custom") {
      start = utcDate(custom.start);
      stop = utcDate(custom.end) + DAY;
    } else if (selection === "ytd") {
      start = utcDate(`${generatedAt.slice(0, 4)}-01-01`);
    } else if (selection === "all") {
      start = earliest ? utcDate(earliest.slice(0, 10)) : end - 30 * DAY;
    } else if (["7", "30", "90"].includes(selection)) {
      start = end - Number(selection) * DAY;
    } else {
      throw new Error("Choose a supported historical period.");
    }
    if (stop > end) throw new Error("Choose complete UTC days; today is not complete.");
    if (start >= stop) throw new Error("The start date must not follow the end date.");
    return { start: dateString(start), end: dateString(stop), days: (stop - start) / DAY };
  }

  function previous(period) {
    return {
      start: dateString(utcDate(period.start) - period.days * DAY),
      end: period.start,
      days: period.days,
    };
  }

  function dates(period) {
    return Array.from({ length: period.days }, (_, offset) =>
      dateString(utcDate(period.start) + offset * DAY),
    );
  }

  function inPeriod(timestamp, period) {
    const day = timestamp?.slice(0, 10);
    return day >= period.start && day < period.end;
  }

  function requestedMonths(index, period) {
    if (index.schema_version !== 1 || !Array.isArray(index.months)) {
      throw new Error("Unsupported dashboard history index.");
    }
    const first = dateString(utcDate(previous(period).start) - DAY).slice(0, 7);
    const last = dateString(utcDate(period.end) - DAY).slice(0, 7);
    return index.months.map((entry) => {
      if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(entry.month)) {
        throw new Error("Invalid dashboard history month.");
      }
      return entry.month;
    }).filter((month) => month >= first && month <= last);
  }

  async function loadPartitions(index, period, readJson) {
    return Promise.all(requestedMonths(index, period).map(async (month) => {
      const partition = await readJson(`data/history/${month.slice(0, 4)}/${month.slice(5)}.json`);
      if (partition.month !== month) throw new Error("Dashboard history month does not match its path.");
      return partition;
    }));
  }

  function mergeRecords(records, identity) {
    return [...new Map(records.map((record) => [identity(record), record])).values()];
  }

  function merge(partitions, metrics, dailyHistory = null) {
    if (dailyHistory && (
      dailyHistory.schema_version !== 1 ||
      !Array.isArray(dailyHistory.snapshots) ||
      !Array.isArray(dailyHistory.daily_activity)
    )) throw new Error("Unsupported daily dashboard history.");
    for (const partition of partitions) {
      if (partition.schema_version !== 1 || !/^\d{4}-\d{2}$/.test(partition.month)) {
        throw new Error("Unsupported dashboard history partition.");
      }
      for (const family of ["account_observations", "daily_activity", "activity_runs", "automation_runs", "operational_observations"]) {
        if (!Array.isArray(partition[family])) throw new Error(`Missing history family: ${family}`);
      }
    }
    const records = (family) => partitions.flatMap((partition) => partition[family]);
    const runIdentity = (run) => `${run.workflow}/${run.id}/${run.attempt || 1}`;
    const account = records("account_observations").map((item) => ({
      ...item, source: "bluesky_snapshot",
    }));
    const activityRuns = mergeRecords(
      [
        ...records("activity_runs"),
        ...(metrics.workflow_activity?.runs || []),
        ...(metrics.provider_pressure?.runs || []).filter((run) => run.id != null),
      ], runIdentity,
    );
    const authoritativeRuns = new Set(activityRuns.filter((run) =>
      run.workflow !== "legacy_activity",
    ).map((run) => `${run.id}/${run.attempt || 1}`));
    return {
      snapshots: mergeRecords(
        [...(dailyHistory?.snapshots || []), ...account, ...(metrics.snapshots || []).filter((item) => item.source === "bluesky_snapshot")],
        (item) => item.period_start,
      ).sort((left, right) => left.collected_at.localeCompare(right.collected_at)),
      daily_activity: mergeRecords(
        [...(dailyHistory?.daily_activity || []), ...records("daily_activity"), ...(metrics.daily_activity || [])], (item) => item.date,
      ).sort((left, right) => left.date.localeCompare(right.date)),
      activity_runs: activityRuns.filter((run) => run.workflow !== "legacy_activity" ||
        !authoritativeRuns.has(`${run.id}/${run.attempt || 1}`)),
      automation_runs: mergeRecords(
        [...records("automation_runs"), ...(metrics.operations?.workflow_runs || [])], runIdentity,
      ),
      operational_observations: mergeRecords(
        records("operational_observations"), (item) => item.period_start,
      ).sort((left, right) => left.collected_at.localeCompare(right.collected_at)),
    };
  }

  function snapshotDelta(snapshots, field, period) {
    const measured = snapshots.filter((item) => Number.isFinite(item[field]));
    const baseline = measured.filter((item) => item.collected_at.slice(0, 10) < period.start).at(-1);
    const current = measured.filter((item) => item.collected_at.slice(0, 10) < period.end).at(-1);
    if (
      !baseline || !current ||
      !inPeriod(current.collected_at, period) ||
      utcDate(period.start) - Date.parse(baseline.collected_at) > DAY ||
      utcDate(period.end) - Date.parse(current.collected_at) > DAY
    ) return null;
    return current[field] - baseline[field];
  }

  function sumCompleteActivity(activity, field, period) {
    if (activity.length !== period.days || activity.some((item) => !Number.isFinite(item[field]))) {
      return null;
    }
    return activity.reduce((total, item) => total + item[field], 0);
  }

  function summary(data, period) {
    const activity = data.daily_activity.filter((item) => inPeriod(item.date, period));
    const completed = data.automation_runs.filter((run) =>
      inPeriod(run.created_at, period) && run.status === "completed" &&
      ["success", "failure"].includes(run.conclusion),
    );
    const successful = completed.filter((run) => run.conclusion === "success").length;
    const posting = data.activity_runs.filter((run) =>
      inPeriod(run.created_at, period) &&
      run.workflow === "bluesky_post_joke" && typeof run.fallthrough === "boolean",
    );
    const fallthroughs = posting.filter((run) => run.fallthrough).length;
    const observedActivity = Object.fromEntries([
      ["jokes", "joke_posts"], ["follows", "follows"],
    ].map(([label, field]) => {
      const measured = activity.filter((item) => Number.isFinite(item[field]));
      return [label, {
        days: measured.length,
        total: measured.length ? measured.reduce((total, item) => total + item[field], 0) : null,
      }];
    }));
    return {
      followers: snapshotDelta(data.snapshots, "followers", period),
      engagement: snapshotDelta(data.snapshots, "engagement_total", period),
      jokes: sumCompleteActivity(activity, "joke_posts", period),
      follows: sumCompleteActivity(activity, "follows", period),
      activityDays: activity.length,
      sampledDays: new Set(data.snapshots.filter((item) =>
        inPeriod(item.collected_at, period),
      ).map((item) => item.collected_at.slice(0, 10))).size,
      observedActivity,
      completed: completed.length || null,
      failed: completed.length ? completed.length - successful : null,
      successRate: completed.length ? successful * 100 / completed.length : null,
      postingRuns: posting.length,
      fallthroughs,
      fallthroughRate: posting.length ? fallthroughs * 100 / posting.length : null,
    };
  }

  function sourceOutcome(observation, source) {
    const checkpoints = (observation?.audience_growth?.cohorts?.periods || [])
      .filter((period) => period.source === source)
      .map((period) => period.checkpoints?.["30"]);
    const observed = checkpoints.reduce((total, checkpoint) => total + (checkpoint?.observed || 0), 0);
    const following = checkpoints.reduce((total, checkpoint) => total + (checkpoint?.still_following || 0), 0);
    return observed ? following * 100 / observed : null;
  }

  function providerSupply(data, period) {
    const runs = data.activity_runs.filter((run) =>
      run.workflow === "bluesky_post_joke" && inPeriod(run.created_at, period),
    );
    const measured = runs.filter((run) => typeof run.posted === "boolean");
    const detailed = measured.filter((run) => Array.isArray(run.provider_candidates));
    const publications = measured.filter((run) => run.posted);
    const sources = new Map();
    publications.forEach((run) => {
      const name = run.successful_source || "unknown";
      sources.set(name, (sources.get(name) || 0) + 1);
    });
    const fields = ["fetches", "candidates", "selected", "published", "duplicate", "too_long", "network_error", "provider_error", "exhausted"];
    const groups = new Map();
    sources.forEach((published, name) => groups.set(name, { name, published, visits: 0, detailed: false }));
    detailed.forEach((run) => {
      run.provider_candidates.forEach((item) => {
        if (fields.some((field) => !Number.isSafeInteger(item[field]) || item[field] < 0)) {
          throw new Error("Invalid provider candidate counters in history.");
        }
        const group = groups.get(item.name) || { name: item.name, published: 0, visits: 0, detailed: false };
        if (!group.detailed) {
          Object.assign(group, Object.fromEntries(fields.filter((field) => field !== "published").map((field) => [field, 0])));
        }
        group.detailed = true;
        group.visits += 1;
        fields.filter((field) => field !== "published").forEach((field) => { group[field] += item[field]; });
        groups.set(item.name, group);
      });
    });
    const providers = [...groups.values()].map((group) => ({
      ...group,
      publicationShare: publications.length ? group.published * 100 / publications.length : null,
      rejectionRate: group.detailed && group.candidates
        ? (group.duplicate + group.too_long) * 100 / group.candidates : null,
      errorRate: group.detailed && group.fetches
        ? (group.network_error + group.provider_error) * 100 / group.fetches : null,
    })).sort((left, right) => right.published - left.published || left.name.localeCompare(right.name));
    const leading = providers[0];
    return {
      postingAttempts: runs.length,
      measuredRuns: measured.length,
      detailedRuns: detailed.length,
      published: publications.length,
      failedPublications: measured.length - publications.length,
      leadingSource: publications.length ? leading.name : null,
      leadingShare: publications.length ? leading.publicationShare : null,
      concentration: publications.length
        ? providers.reduce((sum, item) => sum + (item.published / publications.length) ** 2, 0) : null,
      providers,
    };
  }

  function incidents(data, period) {
    const outcomeAt = (run) => run.updated_at || run.created_at;
    const grouped = new Map();
    data.automation_runs.forEach((run) => {
      if (!grouped.has(run.workflow)) grouped.set(run.workflow, []);
      grouped.get(run.workflow).push(run);
    });
    const episodes = [];
    grouped.forEach((runs, workflow) => {
      let failures = [];
      const save = (recovery) => {
        if (failures.some((run) => inPeriod(outcomeAt(run), period))) {
          episodes.push({
            workflow, failures, recovery,
            first_failure_at: outcomeAt(failures[0]),
            last_failure_at: outcomeAt(failures.at(-1)),
          });
        }
        failures = [];
      };
      runs.sort((left, right) => outcomeAt(left).localeCompare(outcomeAt(right)) ||
        left.id - right.id || (left.attempt || 1) - (right.attempt || 1));
      runs.forEach((run) => {
        if (run.status !== "completed") return;
        if (run.conclusion === "failure") failures.push(run);
        else if (run.conclusion === "success") save(run);
      });
      save(null);
    });
    return episodes.sort((left, right) =>
      right.last_failure_at.localeCompare(left.last_failure_at),
    );
  }

  function series(data, period) {
    const activity = new Map(data.daily_activity.map((item) => [item.date, item]));
    const accounts = new Map();
    const operational = new Map();
    for (const item of data.snapshots) accounts.set(item.collected_at.slice(0, 10), item);
    for (const item of data.operational_observations) {
      operational.set(item.collected_at.slice(0, 10), item);
    }
    return dates(period).map((date) => {
      const daily = activity.get(date);
      const account = accounts.get(date);
      const runs = data.automation_runs.filter((run) =>
        run.created_at?.slice(0, 10) === date && run.status === "completed",
      );
      const posting = data.activity_runs.filter((run) =>
        run.created_at?.slice(0, 10) === date &&
        run.workflow === "bluesky_post_joke" && typeof run.fallthrough === "boolean",
      );
      const supply = providerSupply(data, { start: date, end: dateString(utcDate(date) + DAY), days: 1 });
      return {
        date,
        followers: account?.followers ?? null,
        following: account?.following ?? null,
        profile_posts: account?.profile_posts ?? null,
        engagement_total: account?.engagement_total ?? null,
        joke_posts: daily?.joke_posts ?? null,
        follows: daily?.follows ?? null,
        unfollows: daily?.unfollows ?? null,
        failures: runs.length ? runs.filter((run) => run.conclusion === "failure").length : null,
        fallthroughRate: posting.length
          ? posting.filter((run) => run.fallthrough).length * 100 / posting.length
          : null,
        deliveryRate: operational.get(date)?.posting_delivery?.windows?.["7"]?.delivery_rate ?? null,
        providerLeadingShare: supply.leadingShare,
        providerConcentration: supply.concentration,
        providerRejectionRates: Object.fromEntries(supply.providers.map((item) => [item.name, item.rejectionRate])),
        sourceOutcomes: Object.fromEntries(["followback", "interaction", "discovery"].map((source) =>
          [source, sourceOutcome(operational.get(date), source)],
        )),
      };
    });
  }

  function availability(data) {
    return {
      audience: data.snapshots[0]?.collected_at?.slice(0, 10) || null,
      activity: data.daily_activity[0]?.date || null,
      workflows: data.automation_runs.map((item) => item.created_at).sort()[0]?.slice(0, 10) || null,
      operations: data.operational_observations[0]?.collected_at?.slice(0, 10) || null,
    };
  }

  return { range, previous, dates, inPeriod, requestedMonths, loadPartitions, merge, summary, series, providerSupply, incidents, availability };
})();
