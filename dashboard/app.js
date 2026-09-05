const DATA_URL = "data/metrics.json";
const HISTORY_URL = "data/history/daily.json";
const EMBED_SCRIPT_URL = "https://embed.bsky.app/static/embed.js";
const AVATAR_ORIGIN = "https://cdn.bsky.app";
const colours = ["#087fdb", "#df6255", "#138a78", "#e9aa31", "#08a9cf"];
const charts = {};
let metrics;
let historyMetrics;
let selectedRange = "30";
let selectedTopRange = "30";
let blueskyEmbedLoad;
const dashboardViews = ["audience", "operations"];

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

function safeAvatarUrl(value) {
  try {
    const url = new URL(value);
    return url.origin === AVATAR_ORIGIN ? url.href : "";
  } catch {
    return "";
  }
}

function dashboardViewFromHash() {
  const view = window.location.hash.slice(1);
  return dashboardViews.includes(view) ? view : "audience";
}

function showDashboardView(view) {
  const selectedView = dashboardViews.includes(view) ? view : "audience";
  document.querySelectorAll("[data-dashboard-view]").forEach((tab) => {
    const selected = tab.dataset.dashboardView === selectedView;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
  });
  document.querySelectorAll("[data-dashboard-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.dashboardPanel !== selectedView;
  });
  if (selectedView === "audience") {
    requestAnimationFrame(() => Object.values(charts).forEach((chart) => chart.resize()));
  }
}

function selectDashboardView(view) {
  if (window.location.hash === `#${view}`) showDashboardView(view);
  else window.location.hash = view;
}

function bindDashboardViews() {
  const tabs = [...document.querySelectorAll("[data-dashboard-view]")];
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectDashboardView(tab.dataset.dashboardView));
    tab.addEventListener("keydown", (event) => {
      let targetIndex;
      if (event.key === "ArrowLeft") targetIndex = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === "ArrowRight") targetIndex = (index + 1) % tabs.length;
      else if (event.key === "Home") targetIndex = 0;
      else if (event.key === "End") targetIndex = tabs.length - 1;
      else return;
      event.preventDefault();
      const target = tabs[targetIndex];
      selectDashboardView(target.dataset.dashboardView);
      target.focus();
    });
  });
  window.addEventListener("hashchange", () => showDashboardView(dashboardViewFromHash()));
  showDashboardView(dashboardViewFromHash());
}

function metricText(value) {
  return value == null ? "--" : numberFormat.format(value);
}

function signedNumber(value) {
  return `${value > 0 ? "+" : ""}${numberFormat.format(value)}`;
}

function renderProfile() {
  const profileLink = document.getElementById("profile-link");
  profileLink.href = metrics.account.profile_url;
  document.getElementById("profile-avatar").src = safeAvatarUrl(metrics.account.avatar);
  setText("profile-handle", `@${metrics.account.handle}`);
  setText("collection-time", `Updated ${dateTimeFormat.format(new Date(metrics.generated_at))}`);
}

function createPostEmbed(post) {
  const quote = document.createElement("blockquote");
  quote.className = "bluesky-embed post-fallback";
  quote.dataset.blueskyUri = post.uri;

  const header = document.createElement("div");
  header.className = "post-fallback-header";
  const avatar = document.createElement("img");
  avatar.src = safeAvatarUrl(metrics.account.avatar);
  avatar.alt = "";
  const name = document.createElement("span");
  name.textContent = `${metrics.account.display_name} @${metrics.account.handle}`;
  header.append(avatar, name);

  const text = document.createElement("p");
  text.className = "post-fallback-text";
  text.textContent = post.text;
  const link = document.createElement("a");
  link.href = post.url;
  link.textContent = "View on Bluesky";
  quote.append(header, text, link);
  return quote;
}

function loadBlueskyEmbeds(container = document) {
  if (window.bluesky?.scan) {
    window.bluesky.scan(container);
    return;
  }
  if (!blueskyEmbedLoad) {
    blueskyEmbedLoad = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = EMBED_SCRIPT_URL;
      script.async = true;
      script.addEventListener("load", resolve, { once: true });
      script.addEventListener("error", reject, { once: true });
      document.head.append(script);
    });
  }
  blueskyEmbedLoad
    .then(() => window.bluesky?.scan(container))
    .catch((error) => console.error("Unable to load Bluesky embeds", error));
}

function renderLatestJoke() {
  const latest = metrics.latest_joke;
  setText("latest-date", dateFormat.format(new Date(latest.created_at)));
  const stage = document.getElementById("latest-post");
  stage.replaceChildren(createPostEmbed(latest));
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

function mergeSeries(historical, recent, identity) {
  const merged = new Map(historical.map((item) => [identity(item), item]));
  recent.forEach((item) => merged.set(identity(item), item));
  return [...merged.values()].sort((left, right) =>
    identity(left).localeCompare(identity(right)),
  );
}

function snapshotSeries() {
  if (selectedRange !== "all" || !historyMetrics) return metrics.snapshots;
  return mergeSeries(
    historyMetrics.snapshots,
    metrics.snapshots,
    (item) => item.collected_at,
  );
}

function activitySeries() {
  if (selectedRange !== "all" || !historyMetrics) return metrics.daily_activity;
  return mergeSeries(historyMetrics.daily_activity, metrics.daily_activity, (item) => item.date);
}

async function loadHistory() {
  if (historyMetrics) return true;
  const status = document.getElementById("history-status");
  status.hidden = false;
  status.textContent = "Loading all-time history...";
  try {
    const response = await fetch(HISTORY_URL);
    if (!response.ok) throw new Error(`History request failed: ${response.status}`);
    historyMetrics = await response.json();
    status.hidden = true;
    return true;
  } catch (error) {
    console.error(error);
    status.textContent = "All-time history is unavailable. Select All to retry.";
    return false;
  }
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
  const allSnapshots = snapshotSeries().filter((item) => inRange(item.collected_at));
  const snapshots = allSnapshots.filter((item) =>
    ["bluesky_snapshot", "bluesky_daily"].includes(item.source),
  );
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
      item.source === "bluesky_snapshot"
        ? "Sampled"
        : item.source === "bluesky_daily"
          ? "Daily sample"
          : "Reconstructed",
    ]),
  );
}

function renderActivityChart() {
  const activity = activitySeries().filter((item) => inRange(`${item.date}T23:59:59Z`));
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

function checkpointSummary(periods, source, checkpoint) {
  const values = periods
    .filter((period) => period.source === source)
    .map((period) => period.checkpoints?.[checkpoint] || {});
  const observed = values.reduce((total, value) => total + (value.observed || 0), 0);
  const stillFollowing = values.reduce((total, value) => total + (value.still_following || 0), 0);
  const pending = values.reduce((total, value) => total + (value.pending_due || 0), 0);
  return {
    observed,
    stillFollowing,
    pending,
    rate: observed ? (stillFollowing * 100) / observed : null,
  };
}

function renderAudienceGrowth() {
  const growth = metrics.audience_growth || { net_followers: {}, sources: {}, cohorts: { periods: [] } };
  const periods = growth.cohorts?.periods || [];
  const net7 = growth.net_followers?.["7"];
  const net30 = growth.net_followers?.["30"];
  const engagement30 = metrics.engagement_momentum?.deltas?.["30"];
  setText("growth-net-7", net7 === null || net7 === undefined ? "--" : signedNumber(net7));
  setText("growth-net-30", net30 === null || net30 === undefined ? "--" : signedNumber(net30));
  setText(
    "growth-engagement-30",
    engagement30 === null || engagement30 === undefined ? "--" : signedNumber(engagement30),
  );

  const all30 = ["followback", "interaction", "discovery"].map((source) =>
    checkpointSummary(periods, source, "30"),
  );
  const observed30 = all30.reduce((total, value) => total + value.observed, 0);
  const retained30 = all30.reduce((total, value) => total + value.stillFollowing, 0);
  setText(
    "growth-reciprocity-30",
    observed30 ? `${percentageFormat.format((retained30 * 100) / observed30)}%` : "--",
  );
  setText(
    "growth-reciprocity-note",
    observed30 ? `${numberFormat.format(observed30)} accounts observed` : "Collecting cohort history",
  );
  setText(
    "growth-coverage",
    growth.cohorts?.coverage_started_at
      ? `Cohorts observed since ${dateFormat.format(new Date(growth.cohorts.coverage_started_at))}`
      : "Collecting source and cohort history",
  );

  const denominatorLabels = {
    candidates: "candidates",
    eligible: "eligible accounts",
    selected: "selected accounts",
  };
  ["followback", "interaction", "discovery"].forEach((source) => {
    const values = growth.sources?.[source] || {};
    const checkpoint30 = checkpointSummary(periods, source, "30");
    const checkpoint90 = checkpointSummary(periods, source, "90");
    setText(`growth-${source}-acquired`, metricText(values.acquired));
    setText(
      `growth-${source}-context`,
      values.considered === undefined
        ? "Collecting activity"
        : `of ${numberFormat.format(values.considered)} ${denominatorLabels[values.denominator] || "accounts"}`,
    );
    setText(
      `growth-${source}-success`,
      values.success_rate === null || values.success_rate === undefined
        ? "--"
        : `${percentageFormat.format(values.success_rate)}%`,
    );
    [["30", checkpoint30], ["90", checkpoint90]].forEach(([checkpoint, summary]) => {
      const suffix = summary.pending ? ` · ${summary.pending} due` : "";
      setText(
        `growth-${source}-${checkpoint}`,
        summary.rate === null ? `Collecting${suffix}` : `${percentageFormat.format(summary.rate)}%${suffix}`,
      );
    });
  });

  renderTable(
    "growth-cohort-table",
    periods.map((period) => [
      period.month,
      period.source,
      numberFormat.format(period.acquired),
      numberFormat.format(period.checkpoints["30"].observed),
      period.checkpoints["30"].rate === null ? "--" : `${percentageFormat.format(period.checkpoints["30"].rate)}%`,
      numberFormat.format(period.checkpoints["90"].observed),
      period.checkpoints["90"].rate === null ? "--" : `${percentageFormat.format(period.checkpoints["90"].rate)}%`,
    ]),
  );
  document.getElementById("growth-cohort-details").hidden = periods.length === 0;
}

function renderStarterPackAttribution(starterPacks) {
  const starterPackList = document.getElementById("starter-pack-list");
  const starterPackEmpty = document.getElementById("starter-pack-empty");
  const packs = starterPacks.packs || [];
  starterPackList.replaceChildren();
  setText("starter-pack-total-7", metricText(starterPacks.last_checked_at ? starterPacks.windows?.["7"] : null));
  setText("starter-pack-total-30", metricText(starterPacks.last_checked_at ? starterPacks.windows?.["30"] : null));
  setText(
    "starter-pack-history-note",
    starterPacks.coverage_started_at
      ? `${numberFormat.format(starterPacks.window_days || 30)}-day attributed follows`
      : "Collecting attribution history",
  );
  packs.forEach((pack) => {
    const item = document.createElement("li");
    const link = document.createElement("a");
    const details = document.createElement("span");
    const name = document.createElement("strong");
    const creator = document.createElement("small");
    const count = document.createElement("strong");
    link.href = pack.url;
    link.target = "_blank";
    link.rel = "noreferrer";
    name.textContent = pack.name || "Starter pack";
    creator.textContent = pack.creator_handle ? `by @${pack.creator_handle}` : "View on Bluesky";
    count.textContent = `${numberFormat.format(pack.follows || 0)} · ${percentageFormat.format(pack.share_30_day || 0)}%`;
    details.append(name, creator);
    link.append(details, count);
    item.append(link);
    starterPackList.append(item);
  });
  starterPackEmpty.hidden = packs.length > 0;
}

function renderNetworkMaintenance(network) {
  const responseWindow = network.response_window;
  const unfollow = network.unfollow;
  const hasUnfollowHistory = unfollow?.completed_runs > 0;
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
}

function renderSocialActivity() {
  const starterPacks = metrics.starter_pack_attribution || { packs: [] };
  const network = metrics.network_maintenance || {};
  const unfollow = network.unfollow;
  renderStarterPackAttribution(starterPacks);
  renderNetworkMaintenance(network);
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
  const minimumComparisonPosts = providerMetrics.minimum_comparison_posts || 30;
  const checked = providers.filter(
    (provider) => provider.configured !== false && provider.healthy !== null,
  );
  const healthy = checked.filter((provider) => provider.healthy === true).length;
  setText("providers-healthy", `${healthy}/${checked.length}`);
  setText("retained-publications", numberFormat.format(providerMetrics.retained_publications));

  const pressure = metrics.provider_pressure?.windows || {};
  const sevenDays = pressure["7"];
  const thirtyDays = pressure["30"];
  const hasPressureHistory = sevenDays?.completed_runs > 0;
  setText(
    "provider-pressure-note",
    hasPressureHistory
      ? `${numberFormat.format(sevenDays.completed_runs)} posting runs observed over 7 days`
      : "Posting run history will appear after the next completed run.",
  );
  setText(
    "provider-fallthrough-7",
    hasPressureHistory ? `${percentageFormat.format(sevenDays.fallthrough_rate)}%` : "--",
  );
  setText(
    "provider-fallthrough-runs-7",
    hasPressureHistory
      ? `${numberFormat.format(sevenDays.fallthroughs)} fall-through runs`
      : "-- runs",
  );
  setText(
    "provider-attempts-7",
    hasPressureHistory ? numberFormat.format(sevenDays.average_attempts) : "--",
  );
  setText(
    "provider-static-fallbacks-7",
    hasPressureHistory ? numberFormat.format(sevenDays.static_fallbacks) : "--",
  );
  setText(
    "provider-fallthrough-30",
    thirtyDays?.completed_runs
      ? `${percentageFormat.format(thirtyDays.fallthrough_rate)}%`
      : "--",
  );
  setText(
    "provider-fallthrough-runs-30",
    thirtyDays?.completed_runs
      ? `${numberFormat.format(thirtyDays.fallthroughs)} fall-through runs`
      : "-- runs",
  );
  const rejectionValues = {
    "provider-rejection-duplicate": sevenDays?.rejections?.duplicate,
    "provider-rejection-too-long": sevenDays?.rejections?.too_long,
    "provider-rejection-network": sevenDays?.rejections?.network_error,
    "provider-rejection-provider": sevenDays?.rejections?.provider_error,
  };
  Object.entries(rejectionValues).forEach(([id, value]) => {
    setText(id, metricText(hasPressureHistory ? value : null));
  });
  const starts = Object.entries(sevenDays?.starting_providers || {})
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .map(([name, count]) => `${displayName(name)} ${numberFormat.format(count)}`);
  const sources = Object.entries(sevenDays?.successful_sources || {})
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .map(([name, count]) => `${displayName(name)} ${numberFormat.format(count)}`);
  const sourceSummary = [];
  if (starts.length) sourceSummary.push(`Started: ${starts.join(" · ")}`);
  if (sources.length) sourceSummary.push(`Published: ${sources.join(" · ")}`);
  setText(
    "provider-source-note",
    hasPressureHistory && sourceSummary.length ? sourceSummary.join(" | ") : "--",
  );

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
    const average = document.createElement("span");
    average.className = "sample-cell";
    const averageValue = document.createElement("span");
    averageValue.textContent =
      provider.average_interactions === null
        ? "Collecting"
        : numberFormat.format(provider.average_interactions);
    const sampleSize = document.createElement("small");
    sampleSize.textContent =
      provider.average_interactions === null
        ? `${numberFormat.format(provider.visible_posts)}/${numberFormat.format(minimumComparisonPosts)} visible posts`
        : `${numberFormat.format(provider.visible_posts)} visible posts`;
    average.append(averageValue, sampleSize);
    appendCell(row, average);
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

function renderModerationActivity() {
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
    }

    function renderPostingDelivery() {
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
}

function operationalAlertText(alert) {
  if (alert.kind === "stale_dashboard") return "Dashboard collection is overdue";
  if (alert.kind === "workflow_failure") return `${displayName(alert.workflow)} failed most recently`;
  if (alert.kind === "workflow_overdue") return `${displayName(alert.workflow)} is overdue`;
  if (alert.kind === "provider_health") {
    return `${numberFormat.format(alert.count)} configured provider${alert.count === 1 ? "" : "s"} need attention`;
  }
  if (alert.kind === "posting_delivery") {
    return `${numberFormat.format(alert.count)} posting slot${alert.count === 1 ? "" : "s"} missed in 7 complete days`;
  }
  return "Operational attention needed";
}

function renderOperationalPulse(automation) {
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
      item.textContent = operationalAlertText(alert);
      pulse.append(item);
    });
  }
}

function renderWorkflowTable(workflows) {
  const body = document.querySelector("#workflow-table tbody");
  body.replaceChildren();
  [...workflows]
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

function renderAutomation() {
  const automation = metrics.automation || { workflows: [], alerts: [] };
  setText(
    "automation-rate",
    automation.success_rate === null ? "--" : `${numberFormat.format(automation.success_rate)}%`,
  );
  setText("automation-runs", numberFormat.format(automation.runs));
  setText("automation-failed", numberFormat.format(automation.failed));
  renderModerationActivity();
  renderPostingDelivery();
  renderOperationalPulse(automation);
  renderWorkflowTable(automation.workflows);
}

function renderTopPosts() {
  const container = document.getElementById("top-posts");
  document.getElementById("top-post-range").hidden = !metrics.top_posts_by_window;
  const posts = metrics.top_posts_by_window?.[selectedTopRange] || metrics.top_posts;
  const emptyState = document.getElementById("top-posts-empty");
  container.replaceChildren();
  emptyState.hidden = posts.length > 0;
  posts.forEach((post) => {
    const article = document.createElement("article");
    article.className = "top-post-stage";
    article.append(createPostEmbed(post));
    container.append(article);
  });
  loadBlueskyEmbeds(container);
}

function renderCharts() {
  renderAudienceChart();
  renderActivityChart();
  renderAudienceGrowth();
  renderSocialActivity();
  renderEngagement();
}

function bindRangeControls() {
  document.querySelectorAll("[data-range]").forEach((button) => {
    button.addEventListener("click", async () => {
      selectedRange = button.dataset.range;
      document.querySelectorAll("[data-range]").forEach((item) => {
        const selected = item === button;
        item.classList.toggle("active", selected);
        item.setAttribute("aria-pressed", String(selected));
      });
      if (selectedRange === "all") await loadHistory();
      renderAudienceChart();
      renderActivityChart();
    });
  });
  document.querySelectorAll("[data-top-range]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedTopRange = button.dataset.topRange;
      document.querySelectorAll("[data-top-range]").forEach((item) => {
        const selected = item === button;
        item.classList.toggle("active", selected);
        item.setAttribute("aria-pressed", String(selected));
      });
      renderTopPosts();
    });
  });
}

async function initialise() {
  bindDashboardViews();
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