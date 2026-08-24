const DATA_URL = "data/metrics.json";
const EMBED_SCRIPT_URL = "https://embed.bsky.app/static/embed.js";
const colours = ["#087fdb", "#df6255", "#138a78", "#e9aa31", "#08a9cf"];
const charts = {};
let metrics;
let selectedRange = "30";

const numberFormat = new Intl.NumberFormat("en-GB");
const percentageFormat = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 });
const compactFormat = new Intl.NumberFormat("en-GB", {
  notation: "compact",
  maximumFractionDigits: 1,
});
const dateFormat = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});
const dateTimeFormat = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
  timeZoneName: "short",
});

function setText(id, value) {
  document.getElementById(id).textContent = value;
}

function metricText(value) {
  return value == null ? "--" : numberFormat.format(value);
}

function renderProfile() {
  const profileLink = document.getElementById("profile-link");
  profileLink.href = metrics.account.profile_url;
  document.getElementById("profile-avatar").src = metrics.account.avatar;
  setText("profile-handle", `@${metrics.account.handle}`);
  setText("collection-time", `Updated ${dateTimeFormat.format(new Date(metrics.generated_at))}`);
}

function renderLatestJoke() {
  const latest = metrics.latest_joke;
  setText("latest-date", dateFormat.format(new Date(latest.created_at)));
  const stage = document.getElementById("latest-post");
  stage.replaceChildren();

  const quote = document.createElement("blockquote");
  quote.className = "bluesky-embed post-fallback";
  quote.dataset.blueskyUri = latest.uri;

  const header = document.createElement("div");
  header.className = "post-fallback-header";
  const avatar = document.createElement("img");
  avatar.src = metrics.account.avatar;
  avatar.alt = "";
  const name = document.createElement("span");
  name.textContent = `${metrics.account.display_name} @${metrics.account.handle}`;
  header.append(avatar, name);

  const text = document.createElement("p");
  text.className = "post-fallback-text";
  text.textContent = latest.text;
  const link = document.createElement("a");
  link.href = latest.url;
  link.textContent = "View on Bluesky";
  quote.append(header, text, link);
  stage.append(quote);

  const script = document.createElement("script");
  script.src = EMBED_SCRIPT_URL;
  script.async = true;
  document.head.append(script);
}

function deltaText(current, previous) {
  if (!previous) return "Baseline snapshot";
  const difference = current - previous;
  if (difference === 0) return "No change";
  return `${difference > 0 ? "+" : ""}${numberFormat.format(difference)} since last update`;
}

function renderMetrics() {
  const current = metrics.current;
  const sampledSnapshots = metrics.snapshots.filter((item) => item.source === "bluesky_snapshot");
  const previous = sampledSnapshots.length > 1 ? sampledSnapshots.at(-2) : null;
  setText("followers", compactFormat.format(current.followers));
  setText("following", compactFormat.format(current.following));
  setText("profile-posts", compactFormat.format(current.profile_posts));
  setText("engagement-rate", numberFormat.format(current.engagement_per_joke));
  setText("joke-posts", `Across ${numberFormat.format(current.joke_posts)} jokes`);
  setText("followers-delta", deltaText(current.followers, previous?.followers));
  setText("following-delta", deltaText(current.following, previous?.following));
  setText("posts-delta", deltaText(current.profile_posts, previous?.profile_posts));
}

function cutoffDate() {
  if (selectedRange === "all") return null;
  const cutoff = new Date(metrics.generated_at);
  cutoff.setUTCDate(cutoff.getUTCDate() - Number(selectedRange));
  return cutoff;
}

function inRange(value) {
  const cutoff = cutoffDate();
  return !cutoff || new Date(value) >= cutoff;
}

function replaceChart(name, context, config) {
  charts[name]?.destroy();
  charts[name] = new Chart(context, config);
}

function baseOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { intersect: false, mode: "index" },
    plugins: {
      legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8 } },
      tooltip: { displayColors: true },
    },
    scales: {
      x: { grid: { display: false }, ticks: { maxTicksLimit: 7 } },
      y: { beginAtZero: false, grid: { color: "#e4eaeb" } },
    },
  };
}

function renderAudienceChart() {
  const allSnapshots = metrics.snapshots.filter((item) => inRange(item.collected_at));
  const snapshots = allSnapshots.filter((item) => item.source === "bluesky_snapshot");
  const chartFrame = document.getElementById("audience-chart-frame");
  const chartCanvas = document.getElementById("audience-chart");
  const emptyState = document.getElementById("audience-empty");
  const hasHistory = snapshots.length >= 2;
  chartCanvas.hidden = !hasHistory;
  emptyState.hidden = hasHistory;
  chartFrame.classList.toggle("is-empty", !hasHistory);

  if (!hasHistory) {
    charts.audience?.destroy();
    delete charts.audience;
  } else {
    const baseline = snapshots[0];
    const options = baseOptions();
    options.scales.y.beginAtZero = true;
    options.scales.y.title = { display: true, text: "Change since first sample" };
    options.plugins.tooltip.callbacks = {
      label(context) {
        const absolute = context.dataset.absoluteValues[context.dataIndex];
        const change = context.parsed.y;
        return `${context.dataset.label}: ${change >= 0 ? "+" : ""}${numberFormat.format(change)} (${numberFormat.format(absolute)} total)`;
      },
    };
    replaceChart("audience", chartCanvas, {
      type: "line",
      data: {
        labels: snapshots.map((item) => dateTimeFormat.format(new Date(item.collected_at))),
        datasets: [
          {
            label: "Followers",
            data: snapshots.map((item) => item.followers - baseline.followers),
            absoluteValues: snapshots.map((item) => item.followers),
            borderColor: colours[0],
            backgroundColor: colours[0],
            tension: 0.25,
          },
          {
            label: "Following",
            data: snapshots.map((item) => item.following - baseline.following),
            absoluteValues: snapshots.map((item) => item.following),
            borderColor: colours[2],
            backgroundColor: colours[2],
            tension: 0.25,
          },
        ],
      },
      options,
    });
  }
  renderTable(
    "audience-table",
    allSnapshots.map((item) => [
      dateTimeFormat.format(new Date(item.collected_at)),
      metricText(item.followers),
      metricText(item.following),
      metricText(item.profile_posts),
      item.source === "bluesky_snapshot" ? "Sampled" : "Reconstructed",
    ]),
  );
}

function renderActivityChart() {
  const activity = metrics.daily_activity.filter((item) => inRange(`${item.date}T23:59:59Z`));
  const options = baseOptions();
  options.scales.y.beginAtZero = true;
  options.scales.y.ticks = { precision: 0 };
  replaceChart("activity", document.getElementById("activity-chart"), {
    type: "bar",
    data: {
      labels: activity.map((item) => dateFormat.format(new Date(`${item.date}T00:00:00Z`))),
      datasets: [
        { label: "Joke posts", data: activity.map((item) => item.joke_posts), backgroundColor: colours[0] },
        { label: "Follows", data: activity.map((item) => item.follows ?? 0), backgroundColor: colours[2] },
        { label: "Unfollows", data: activity.map((item) => item.unfollows), backgroundColor: colours[1] },
      ],
    },
    options,
  });
  renderTable(
    "activity-table",
    activity.map((item) => [item.date, item.joke_posts, item.follows ?? 0, item.unfollows]),
  );
}

function renderDiscovery() {
  const discovery = metrics.discovery_activity || {
    runs: [],
    followed: 0,
    completed_runs: 0,
    completion_rate: null,
    median_per_run: null,
    average_per_run: null,
    zero_result_runs: 0,
    coverage_start: null,
  };
  const runs = discovery.runs;
  setText("discovery-followed", numberFormat.format(discovery.followed));
  setText("discovery-runs", numberFormat.format(discovery.completed_runs));
  setText(
    "discovery-completion",
    discovery.completion_rate === null ? "--" : `${percentageFormat.format(discovery.completion_rate)}%`,
  );
  setText(
    "discovery-median",
    discovery.median_per_run === null ? "--" : numberFormat.format(discovery.median_per_run),
  );
  setText(
    "discovery-average",
    discovery.average_per_run === null
      ? "Median accounts added"
      : `${numberFormat.format(discovery.average_per_run)} average per run`,
  );
  setText(
    "discovery-zero-runs",
    discovery.completed_runs
      ? `${numberFormat.format(discovery.zero_result_runs)} zero-result runs`
      : "No run history yet",
  );
  setText(
    "discovery-coverage",
    discovery.coverage_start
      ? `Since ${dateFormat.format(new Date(discovery.coverage_start))}`
      : "Collecting history",
  );

  const chartFrame = document.getElementById("discovery-chart-frame");
  const chartCanvas = document.getElementById("discovery-chart");
  const emptyState = document.getElementById("discovery-empty");
  const dataDetails = document.getElementById("discovery-details");
  const hasRuns = runs.length > 0;
  chartCanvas.hidden = !hasRuns;
  emptyState.hidden = hasRuns;
  dataDetails.hidden = !hasRuns;
  chartFrame.classList.toggle("is-empty", !hasRuns);

  if (hasRuns) {
    const options = baseOptions();
    options.scales.y.beginAtZero = true;
    options.scales.y.ticks = { precision: 0 };
    replaceChart("discovery", chartCanvas, {
      type: "bar",
      data: {
        labels: runs.map((run) => dateTimeFormat.format(new Date(run.created_at))),
        datasets: [
          { label: "Considered", data: runs.map((run) => run.selected), backgroundColor: colours[3] },
          { label: "Added", data: runs.map((run) => run.followed), backgroundColor: colours[2] },
        ],
      },
      options,
    });
  } else {
    charts.discovery?.destroy();
    delete charts.discovery;
    emptyState.textContent = discovery.completed_runs
      ? "No completed discovery runs in this period."
      : "Discovery history will appear after the next completed run.";
  }
  renderTable(
    "discovery-table",
    runs.map((run) => [
      dateTimeFormat.format(new Date(run.created_at)),
      numberFormat.format(run.selected),
      numberFormat.format(run.followed),
      run.selected ? `${percentageFormat.format((run.followed * 100) / run.selected)}%` : "--",
    ]),
  );
}

function renderSocialActivity() {
  const social = metrics.social_activity || { completed_runs: 0, runs: [] };
  const network = metrics.network_maintenance || {};
  const responseWindow = network.response_window;
  const unfollow = network.unfollow;
  const hasSocialHistory = social.completed_runs > 0;
  const hasUnfollowHistory = unfollow?.completed_runs > 0;
  const socialValues = {
    "social-follow-candidates": hasSocialHistory ? social.follow_back_candidates : null,
    "social-follow-added": hasSocialHistory ? social.follow_back_added : null,
    "social-interaction-candidates": hasSocialHistory ? social.interaction_candidates : null,
    "social-interaction-eligible": hasSocialHistory ? social.interaction_eligible : null,
    "social-interaction-added": hasSocialHistory ? social.interaction_added : null,
    "social-interactions-liked": hasSocialHistory ? social.interactions_liked : null,
  };
  Object.entries(socialValues).forEach(([id, value]) => setText(id, metricText(value)));
  setText(
    "social-history-note",
    hasSocialHistory
      ? `${numberFormat.format(social.completed_runs)} runs observed over 30 days`
      : "Social run history will appear after the next completed run.",
  );
  setText(
    "social-protected",
    hasSocialHistory
      ? `${numberFormat.format(social.protected)} protected or previously handled`
      : "-- protected or previously handled",
  );
  setText(
    "social-failed",
    hasSocialHistory
      ? `${numberFormat.format(social.failed)} failed actions`
      : "-- failed actions",
  );
  const maximum = Math.max(
    1,
    ...Object.values(socialValues).map((value) => Number(value) || 0),
  );
  document.querySelectorAll(".social-flow-row").forEach((row) => {
    const value = Number(socialValues[row.dataset.metric]) || 0;
    row.style.setProperty("--flow-width", `${(value * 100) / maximum}%`);
  });

  setText("response-window-active", metricText(responseWindow?.active));
  setText("response-discovery", metricText(responseWindow?.by_source?.discovery));
  setText("response-interaction", metricText(responseWindow?.by_source?.interaction));
  setText("response-other", metricText(responseWindow?.by_source?.other));
  setText("unfollow-processed", metricText(hasUnfollowHistory ? unfollow.processed : null));
  setText("unfollow-completed", metricText(hasUnfollowHistory ? unfollow.unfollowed : null));
  setText("unfollow-pending", metricText(hasUnfollowHistory ? unfollow.cap_remaining : null));
  setText(
    "unfollow-exceptions",
    hasUnfollowHistory
      ? numberFormat.format(unfollow.failed + unfollow.missing_records)
      : "--",
  );
  setText(
    "unfollow-history-note",
    hasUnfollowHistory
      ? `${numberFormat.format(unfollow.completed_runs)} runs observed · ${numberFormat.format(unfollow.stopped_early_runs)} stopped early`
      : "Maintenance history will appear after the next completed run.",
  );

  renderTable(
    "social-table",
    (social.runs || []).map((run) => [
      dateTimeFormat.format(new Date(run.created_at)),
      run.follow_back_candidates,
      run.follow_back_added,
      run.interaction_candidates,
      run.interaction_added,
      run.interactions_liked,
      run.failed,
    ]),
  );
  renderTable(
    "unfollow-table",
    (unfollow?.runs || []).map((run) => [
      dateTimeFormat.format(new Date(run.created_at)),
      run.eligible,
      run.processed,
      run.unfollowed,
      run.failed + run.missing_records,
      run.stopped_early ? "Yes" : "No",
    ]),
  );
}

function renderTable(id, rows) {
  const body = document.querySelector(`#${id} tbody`);
  body.replaceChildren();
  rows.forEach((row) => {
    const tableRow = document.createElement("tr");
    row.forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      tableRow.append(cell);
    });
    body.append(tableRow);
  });
}

function renderEngagement() {
  const entries = Object.entries(metrics.current.engagement);
  const total = entries.reduce((sum, [, count]) => sum + count, 0);
  setText("engagement-total", numberFormat.format(total));
  const momentum = metrics.engagement_momentum?.deltas || {};
  const momentumText = (value) => {
    if (value == null) return "--";
    return `${value > 0 ? "+" : ""}${numberFormat.format(value)}`;
  };
  setText("engagement-change-7", momentumText(momentum["7"]));
  setText("engagement-change-30", momentumText(momentum["30"]));
  setText(
    "engagement-history-note",
    momentum["30"] != null
      ? "Changes in visible joke engagement between sampled totals"
      : "Collecting sampled history; removed or hidden posts can reduce totals",
  );
  replaceChart("engagement", document.getElementById("engagement-chart"), {
    type: "doughnut",
    data: {
      labels: entries.map(([name]) => name),
      datasets: [{ data: entries.map(([, count]) => count), backgroundColor: colours, borderWidth: 0 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "66%",
      plugins: { legend: { display: false } },
    },
  });
  const legend = document.getElementById("engagement-legend");
  legend.replaceChildren();
  entries.forEach(([name, count], index) => {
    const row = document.createElement("div");
    row.className = "legend-row";
    const swatch = document.createElement("span");
    swatch.className = "legend-swatch";
    swatch.style.background = colours[index];
    const label = document.createElement("span");
    label.textContent = name[0].toUpperCase() + name.slice(1);
    const value = document.createElement("strong");
    value.textContent = numberFormat.format(count);
    row.append(swatch, label, value);
    legend.append(row);
  });
}

function displayName(value) {
  const names = {
    api_ninjas: "API Ninjas",
    bluesky_dashboard: "Dashboard",
    bluesky_follow_fellows: "Follow fellows",
    bluesky_follows_and_likes: "Follows and likes",
    bluesky_manage_starter_pack: "Starter pack",
    bluesky_post_joke: "Post joke",
    bluesky_process_reports: "Process reports",
    bluesky_unfollow: "Unfollow",
    bluesky_validate_unfollow_ignore: "Validate unfollow ignore",
    codeql: "CodeQL",
    groandeck: "GroanDeck",
    icanhazdadjoke: "icanhazdadjoke",
    jokeapi: "JokeAPI",
    pr_auto_merge: "PR auto-merge",
    provider_health_check: "Provider health",
    python_tests: "Python tests",
    ruff_quality: "Ruff quality",
    syrsly: "Syrsly",
    validate_runtime_config: "Runtime config",
  };
  return names[value] || value.replaceAll("_", " ");
}

function appendCell(row, value, className) {
  const cell = document.createElement("td");
  if (className) cell.className = className;
  if (value instanceof Node) cell.append(value);
  else cell.textContent = value;
  row.append(cell);
}

function providerHealth(provider) {
  if (provider.configured === false) return { label: "Not configured", className: "unknown" };
  if (provider.healthy === true) return { label: "Healthy", className: "healthy" };
  if (provider.healthy === false) return { label: "Attention", className: "attention" };
  return { label: "No check", className: "unknown" };
}

function rejectionSummary(counts) {
  const labels = {
    duplicate: "duplicate",
    too_long: "too long",
    network_error: "network",
    provider_error: "provider",
  };
  const parts = Object.entries(counts || {})
    .filter(([, count]) => count > 0)
    .map(([reason, count]) => `${numberFormat.format(count)} ${labels[reason] || reason}`);
  return parts.length ? parts.join(" · ") : "--";
}

function durationText(seconds) {
  if (seconds == null) return "--";
  if (seconds < 60) return `${numberFormat.format(seconds)} sec`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${numberFormat.format(minutes)} min`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours} hr ${remainder} min` : `${hours} hr`;
}

function renderProviders() {
  const providerMetrics = metrics.providers;
  const providers = providerMetrics.providers;
  const checked = providers.filter(
    (provider) => provider.configured !== false && provider.healthy !== null,
  );
  const healthy = checked.filter((provider) => provider.healthy === true).length;
  setText("providers-healthy", `${healthy}/${checked.length}`);
  setText("retained-publications", numberFormat.format(providerMetrics.retained_publications));

  const body = document.querySelector("#provider-table tbody");
  body.replaceChildren();
  providers.forEach((provider) => {
    const row = document.createElement("tr");
    const providerName = document.createElement("div");
    providerName.className = "provider-name";
    const name = document.createElement("strong");
    name.textContent = displayName(provider.name);
    const share = providerMetrics.retained_publications
      ? (provider.published * 100) / providerMetrics.retained_publications
      : 0;
    const bar = document.createElement("span");
    bar.className = "provider-share";
    bar.style.setProperty("--provider-share", `${share}%`);
    providerName.append(name, bar);
    if (provider.last_failure_reason) {
      const reason = document.createElement("small");
      reason.textContent = provider.last_failure_reason;
      providerName.append(reason);
    }
    appendCell(row, providerName);
    appendCell(row, numberFormat.format(provider.published));
    appendCell(
      row,
      provider.average_interactions === null
        ? "--"
        : numberFormat.format(provider.average_interactions),
    );
    appendCell(row, numberFormat.format(provider.fallthroughs));
    appendCell(row, rejectionSummary(provider.rejection_counts), "rejection-summary");
    const health = providerHealth(provider);
    const badge = document.createElement("span");
    badge.className = `health-badge ${health.className}`;
    badge.textContent = health.label;
    appendCell(row, badge);
    body.append(row);
  });
}

function renderAutomation() {
  const automation = metrics.automation || { workflows: [], alerts: [] };
  setText(
    "automation-rate",
    automation.success_rate === null ? "--" : `${numberFormat.format(automation.success_rate)}%`,
  );
  setText("automation-runs", numberFormat.format(automation.runs));
  setText("automation-failed", numberFormat.format(automation.failed));

  const moderation = metrics.moderation_activity || { completed_runs: 0 };
  const hasModerationHistory = moderation.completed_runs > 0;
  setText(
    "moderation-proposals",
    metricText(hasModerationHistory ? moderation.proposals : null),
  );
  setText(
    "moderation-acknowledgements",
    metricText(hasModerationHistory ? moderation.acknowledgements : null),
  );
  setText(
    "moderation-removals",
    metricText(hasModerationHistory ? moderation.approved_removals : null),
  );
  setText(
    "moderation-unresolved",
    metricText(hasModerationHistory ? moderation.unresolved : null),
  );
  setText(
    "moderation-history-note",
    hasModerationHistory
      ? `${numberFormat.format(moderation.completed_runs)} report workflow runs observed over 30 days`
      : "Report workflow history will appear after the next completed run.",
  );

  const delivery = metrics.posting_delivery;
  const sevenDays = delivery?.windows?.["7"];
  const thirtyDays = delivery?.windows?.["30"];
  setText(
    "posting-delivery-rate",
    sevenDays?.delivery_rate == null
      ? "--"
      : `${percentageFormat.format(sevenDays.delivery_rate)}%`,
  );
  setText(
    "posting-delivered",
    sevenDays ? `${numberFormat.format(sevenDays.delivered)}/${numberFormat.format(sevenDays.expected)}` : "--",
  );
  setText(
    "posting-delivery-rate-30",
    thirtyDays?.delivery_rate == null
      ? "30 days: --"
      : `30 days: ${percentageFormat.format(thirtyDays.delivery_rate)}%`,
  );
  setText(
    "posting-delivered-30",
    thirtyDays
      ? `30 days: ${numberFormat.format(thirtyDays.delivered)}/${numberFormat.format(thirtyDays.expected)}`
      : "30 days: --",
  );
  setText("posting-missed", sevenDays ? numberFormat.format(sevenDays.missed) : "--");
  setText(
    "posting-missed-context",
    sevenDays && thirtyDays
      ? `${numberFormat.format(sevenDays.delayed)} delayed · 30 days: ${numberFormat.format(thirtyDays.missed)} missed, ${numberFormat.format(thirtyDays.delayed)} delayed`
      : "Delayed slots unavailable",
  );
  setText(
    "posting-streak",
    delivery ? numberFormat.format(delivery.current_streak) : "--",
  );

  const alerts = [...(automation.alerts || [])];
  if (Date.now() - new Date(metrics.generated_at).getTime() > 8 * 60 * 60 * 1000) {
    alerts.unshift({ kind: "stale_dashboard", level: "attention" });
  }
  const pulse = document.getElementById("operational-pulse");
  pulse.replaceChildren();
  if (!alerts.length) {
    const clear = document.createElement("p");
    clear.className = "pulse-clear";
    clear.textContent = "No current operational alerts";
    pulse.append(clear);
  } else {
    alerts.forEach((alert) => {
      const item = document.createElement("p");
      item.className = `pulse-alert ${alert.level || "attention"}`;
      if (alert.kind === "stale_dashboard") {
        item.textContent = "Dashboard collection is overdue";
      } else if (alert.kind === "workflow_failure") {
        item.textContent = `${displayName(alert.workflow)} failed most recently`;
      } else if (alert.kind === "workflow_overdue") {
        item.textContent = `${displayName(alert.workflow)} is overdue`;
      } else if (alert.kind === "provider_health") {
        item.textContent = `${numberFormat.format(alert.count)} configured provider${alert.count === 1 ? "" : "s"} need attention`;
      } else if (alert.kind === "posting_delivery") {
        item.textContent = `${numberFormat.format(alert.count)} posting slot${alert.count === 1 ? "" : "s"} missed in 7 complete days`;
      } else {
        item.textContent = "Operational attention needed";
      }
      pulse.append(item);
    });
  }

  const body = document.querySelector("#workflow-table tbody");
  body.replaceChildren();
  [...automation.workflows]
    .sort((left, right) => right.runs - left.runs || left.name.localeCompare(right.name))
    .forEach((workflow) => {
      const row = document.createElement("tr");
      appendCell(row, displayName(workflow.name));
      appendCell(row, numberFormat.format(workflow.runs));
      const completed = workflow.successful + workflow.failed;
      appendCell(
        row,
        completed ? `${percentageFormat.format((workflow.successful * 100) / completed)}%` : "--",
      );
      appendCell(row, numberFormat.format(workflow.failed), workflow.failed ? "failure-count" : "");
      const runtime = document.createElement("span");
      runtime.className = "runtime-cell";
      const runtimeMedian = document.createElement("span");
      runtimeMedian.textContent = `${durationText(workflow.median_duration_seconds)} median`;
      const runtimeLatest = document.createElement("small");
      runtimeLatest.textContent = `${durationText(workflow.latest_duration_seconds)} latest`;
      runtime.append(runtimeMedian, runtimeLatest);
      appendCell(row, runtime);
      const latest = document.createElement("span");
      const latestState = workflow.last_conclusion || workflow.last_status || "unknown";
      const latestLabels = {
        in_progress: "In progress",
        queued: "Queued",
        requested: "Queued",
        waiting: "Waiting",
        pending: "Pending",
        unknown: workflow.runs ? "Unknown" : "No runs",
      };
      latest.className = `run-status ${latestState}`;
      latest.textContent = latestLabels[latestState] || latestState;
      appendCell(row, latest);
      body.append(row);
    });
}

function renderTopPosts() {
  const container = document.getElementById("top-posts");
  container.replaceChildren();
  metrics.top_posts.forEach((post) => {
    const article = document.createElement("article");
    article.className = "top-post";
    const text = document.createElement("p");
    text.className = "top-post-text";
    text.textContent = post.text;
    const footer = document.createElement("div");
    footer.className = "top-post-footer";
    const interactions = Object.values(post.engagement).reduce((sum, count) => sum + count, 0);
    const score = document.createElement("span");
    score.textContent = `${numberFormat.format(interactions)} interactions`;
    const link = document.createElement("a");
    link.href = post.url;
    link.textContent = "View post";
    footer.append(score, link);
    article.append(text, footer);
    container.append(article);
  });
}

function renderCharts() {
  renderAudienceChart();
  renderActivityChart();
  renderDiscovery();
  renderSocialActivity();
  renderEngagement();
}

function bindRangeControls() {
  document.querySelectorAll("[data-range]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedRange = button.dataset.range;
      document.querySelectorAll("[data-range]").forEach((item) => {
        item.classList.toggle("active", item === button);
      });
      renderAudienceChart();
      renderActivityChart();
      renderDiscovery();
    });
  });
}

async function initialise() {
  try {
    const response = await fetch(DATA_URL);
    if (!response.ok) throw new Error(`Metrics request failed: ${response.status}`);
    metrics = await response.json();
    renderProfile();
    renderLatestJoke();
    renderMetrics();
    renderCharts();
    renderProviders();
    renderAutomation();
    renderTopPosts();
    bindRangeControls();
  } catch (error) {
    console.error(error);
    document.getElementById("page-error").hidden = false;
    setText("collection-time", "Statistics unavailable");
  }
}

initialise();