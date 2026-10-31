const DATA_URL = "data/metrics.json";
const EMBED_SCRIPT_URL = "https://embed.bsky.app/static/embed.js";
const AVATAR_ORIGIN = "https://cdn.bsky.app";
const colours = ["#087fdb", "#df6255", "#138a78", "#e9aa31", "#08a9cf"];
const charts = {};
let metrics;
let selectedTopRange = "30";
let selectedPerformanceAge = "24";
let blueskyEmbedLoad;
const dashboardViews = ["audience", "operations"];
const historicalViews = {
  audience: { selection: "30", period: null, data: null, revision: 0 },
  operations: { selection: "30", period: null, data: null, revision: 0 },
};
const historyRequests = new Map();

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
  requestAnimationFrame(() => Object.values(charts).forEach((chart) => chart.resize()));
  if (metrics && selectedView === "operations" && !historicalViews.operations.revision) {
    void updateHistoricalView("operations", "30");
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

function inRange(value) {
  return DashboardHistory.inPeriod(
    value,
    historicalViews.audience.period || DashboardHistory.range("30", metrics.generated_at),
  );
}

function snapshotSeries() {
  const view = historicalViews.audience;
  if (!view.data) return metrics.snapshots;
  const period = view.period;
  const daily = DashboardHistory.series(view.data, period);
  const recent = DashboardHistory.range("30", metrics.generated_at).start;
  return daily.flatMap((day) => {
    const samples = view.data.snapshots.filter((item) => item.collected_at.slice(0, 10) === day.date);
    if (!samples.length) {
      return [{ collected_at: `${day.date}T00:00:00Z`, source: "missing", followers: null, following: null }];
    }
    return day.date < recent
      ? [{ ...samples.at(-1), source: "bluesky_daily" }]
      : samples;
  });
}

function activitySeries() {
  const view = historicalViews.audience;
  return view.data ? DashboardHistory.series(view.data, view.period) : metrics.daily_activity;
}

async function readHistoryJson(url) {
  if (!historyRequests.has(url)) {
    historyRequests.set(url, fetch(url).then(async (response) => {
      if (!response.ok) throw new Error(`History request failed: ${response.status}`);
      return response.json();
    }).catch((error) => {
      historyRequests.delete(url);
      throw error;
    }));
  }
  return historyRequests.get(url);
}

function historyComparison(current, previous, rate = false) {
  if (current == null || previous == null) return "Comparison unavailable";
  const change = current - previous;
  if (rate) return `${change > 0 ? "+" : ""}${percentageFormat.format(change)} percentage points vs previous period`;
  const relative = previous > 0
    ? ` (${signedNumber(Math.round(change * 1000 / previous) / 10)}%)`
    : "";
  return `${signedNumber(change)}${relative} vs previous period (${numberFormat.format(previous)})`;
}

function renderHistorySummary(viewName) {
  const view = historicalViews[viewName];
  const current = DashboardHistory.summary(view.data, view.period);
  const prior = DashboardHistory.summary(view.data, DashboardHistory.previous(view.period));
  const end = new Date(`${view.period.end}T00:00:00Z`);
  end.setUTCDate(end.getUTCDate() - 1);
  setText(`${viewName}-history-period`, `${dateFormat.format(new Date(`${view.period.start}T00:00:00Z`))} to ${dateFormat.format(end)} · complete UTC days`);
  const available = DashboardHistory.availability(view.data);
  const coverage = viewName === "audience"
    ? `${current.sampledDays}/${view.period.days} days sampled; ${current.activityDays}/${view.period.days} activity days. Loaded audience samples from ${available.audience || "unavailable"}; activity from ${available.activity || "unavailable"}.`
    : `Loaded workflow observations from ${available.workflows || "unavailable"}; operational snapshots from ${available.operations || "unavailable"}. ${current.postingRuns} posting runs have pressure telemetry.`;
  setText(`${viewName}-history-coverage`, `${coverage} Gaps are not zeroes. Comparisons use the preceding ${view.period.days} complete days.`);
  const fields = viewName === "audience"
    ? ["followers", "jokes", "follows", "engagement"]
    : ["completed", "failed", "successRate", "fallthroughRate"];
  fields.forEach((field) => {
    const rate = field.endsWith("Rate");
    const value = current[field];
    const partial = current.observedActivity[field];
    const displayed = value ?? partial?.total;
    setText(`${viewName}-history-${field}`, displayed == null ? "--" : `${numberFormat.format(Math.round(displayed * 10) / 10)}${rate ? "%" : ""}`);
    const comparison = value == null && partial?.total != null
      ? `Observed subtotal: ${partial.days}/${view.period.days} days; comparison unavailable`
      : historyComparison(value, prior[field], rate);
    setText(`${viewName}-history-${field}-comparison`, comparison);
  });
}

function renderOperationalHistory() {
  const view = historicalViews.operations;
  const daily = DashboardHistory.series(view.data, view.period);
  const labels = daily.map((item) => item.date);
  const options = baseOptions();
  options.plugins.legend.labels.color = "#b8cedd";
  Object.values(options.scales).forEach((scale) => {
    scale.ticks = { ...scale.ticks, color: "#b8cedd" };
    scale.grid.color = "#31516a";
  });
  options.scales.y.beginAtZero = true;
  options.scales.y.ticks.precision = 0;
  replaceChart("workflowHistory", document.getElementById("workflow-history-chart"), {
    type: "bar",
    data: { labels, datasets: [{ label: "Failed workflow attempts", data: daily.map((item) => item.failures), backgroundColor: colours[1] }] },
    options,
  });
  const rates = baseOptions();
  rates.plugins.legend.labels.color = "#b8cedd";
  rates.scales.x.ticks.color = "#b8cedd";
  rates.scales.y = {
    min: 0, max: 100,
    ticks: { color: "#b8cedd" },
    grid: { color: "#31516a" },
    title: { display: true, text: "Percent", color: "#b8cedd" },
  };
  replaceChart("pressureHistory", document.getElementById("pressure-history-chart"), {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Daily posting-run fall-through", data: daily.map((item) => item.fallthroughRate), borderColor: colours[1], spanGaps: false },
        { label: "Sampled rolling 7-day slot delivery", data: daily.map((item) => item.deliveryRate), borderColor: colours[0], spanGaps: false },
      ],
    },
    options: rates,
  });
  replaceChart("sourceHistory", document.getElementById("source-history-chart"), {
    type: "line",
    data: {
      labels,
      datasets: ["followback", "interaction", "discovery"].map((source, index) => ({
        label: source === "followback" ? "Existing follower retention" : `${displayName(source)} reciprocity`,
        data: daily.map((item) => item.sourceOutcomes[source]),
        borderColor: colours[index],
        spanGaps: false,
      })),
    },
    options: rates,
  });
  renderProviderSupply(daily, rates);
  renderIncidentHistory();
  const events = view.data.activity_runs.filter((run) =>
    run.workflow === "bluesky_unfollow" && run.unfollows > 0 &&
    DashboardHistory.inPeriod(run.created_at, view.period),
  ).sort((left, right) => left.created_at.localeCompare(right.created_at));
  const list = document.getElementById("history-maintenance-events");
  list.replaceChildren();
  events.forEach((event) => {
    const item = document.createElement("li");
    item.textContent = `${dateTimeFormat.format(new Date(event.created_at))}: ${numberFormat.format(event.unfollows)} unfollows completed`;
    list.append(item);
  });
  document.getElementById("history-maintenance-empty").hidden = events.length > 0;
}

function runLink(run, label) {
  const link = document.createElement("a");
  if (!Number.isSafeInteger(run.id) || run.id <= 0 || !Number.isSafeInteger(run.attempt || 1) || (run.attempt || 1) < 1) {
    throw new Error("Invalid workflow run identity.");
  }
  link.href = `https://github.com/chris-gillatt/thejokebot/actions/runs/${run.id}/attempts/${run.attempt || 1}`;
  link.textContent = label;
  return link;
}

function renderIncidentHistory() {
  const view = historicalViews.operations;
  const episodes = DashboardHistory.incidents(view.data, view.period);
  const body = document.querySelector("#incident-table tbody");
  body.replaceChildren();
  episodes.forEach((episode) => {
    const row = document.createElement("tr");
    const ci = (metrics.operations?.ci_workflows || []).includes(episode.workflow);
    appendCell(row, `${displayName(episode.workflow)} (${ci ? "CI" : "production"})`);
    appendCell(row, `${dateTimeFormat.format(new Date(episode.first_failure_at))} – ${dateTimeFormat.format(new Date(episode.last_failure_at))}`);
    const links = document.createElement("div");
    episode.failures.forEach((run) => {
      const entry = document.createElement("p");
      entry.append(runLink(run, `Run ${run.id}, attempt ${run.attempt || 1}`));
      const steps = document.createElement("span");
      steps.textContent = run.failed_steps?.length
        ? ` · ${run.failed_steps.map((step) => step.name).join("; ")}`
        : " · Failed step unavailable";
      entry.append(steps);
      links.append(entry);
    });
    appendCell(row, links);
    appendCell(row, episode.recovery
      ? runLink(episode.recovery, `Successful run ${episode.recovery.id} (${dateTimeFormat.format(new Date(episode.recovery.updated_at || episode.recovery.created_at))})`)
      : "No successful recovery observed in loaded history");
    body.append(row);
  });
  document.getElementById("incident-empty").hidden = episodes.length > 0;
}

function renderComponentFreshness() {
  const body = document.querySelector("#component-freshness-table tbody");
  body.replaceChildren();
  (metrics.operations?.components || []).forEach((component) => {
    const row = document.createElement("tr");
    appendCell(row, component.name);
    appendCell(row, component.observed_at ? dateTimeFormat.format(new Date(component.observed_at)) : "Not observed");
    appendCell(row, component.last_success_at ? dateTimeFormat.format(new Date(component.last_success_at)) : "Not observed / not applicable");
    let status = "Unavailable";
    if (component.observed_at) status = component.overdue ? "Overdue at collection" : "Observed at collection";
    appendCell(row, status);
    body.append(row);
  });
  const checkpoint = metrics.operations?.components?.find((item) => item.name === "Joke-request checkpoint");
  setText("production-checkpoint", checkpoint?.observed_at ? dateTimeFormat.format(new Date(checkpoint.observed_at)) : "Not observed");
  setText("production-moderation", metricText(metrics.moderation_activity?.unresolved));
  const moderation = metrics.operations?.components?.find((item) => item.name === "Moderation summary");
  setText("production-moderation-note", moderation?.observed_at ? `At ${dateTimeFormat.format(new Date(moderation.observed_at))}; not a live queue` : "Summary observation unavailable");
  const bodySlots = document.querySelector("#slot-exceptions-table tbody");
  bodySlots.replaceChildren();
  const observedExceptions = metrics.posting_delivery?.closed_slot_exceptions;
  const exceptions = observedExceptions || [];
  setText("slot-exceptions-summary", observedExceptions
    ? `${numberFormat.format(exceptions.length)} closed-slot exceptions in the recent 30 days`
    : "Closed-slot exceptions (detail unavailable)");
  setText("slot-exceptions-empty", observedExceptions
    ? "No missed or delayed closed slots observed in the retained 30-day window."
    : "Closed-slot exception detail unavailable in this metrics snapshot.");
  exceptions.forEach((slot) => {
    const row = document.createElement("tr");
    appendCell(row, dateTimeFormat.format(new Date(slot.slot_at)));
    appendCell(row, slot.outcome === "delayed" ? "Delayed (more than 30 minutes)" : "Missed within matching window");
    appendCell(row, slot.published_at ? dateTimeFormat.format(new Date(slot.published_at)) : "No matching publication observed");
    bodySlots.append(row);
  });
  document.getElementById("slot-exceptions-empty").hidden = exceptions.length > 0;
}

function providerSupplyCells(row, provider, prior) {
  appendCell(row, displayName(provider.name));
  const share = provider.publicationShare == null ? "--" : `${percentageFormat.format(provider.publicationShare)}%`;
  appendCell(row, `${provider.published} (${share})`);
  appendCell(row, provider.detailed ? `${provider.visits} / ${provider.fetches}` : "Not measured");
  appendCell(row, provider.detailed ? `${provider.selected} / ${provider.candidates}` : "Not measured");
  appendCell(row, provider.rejectionRate == null ? "--" : `${percentageFormat.format(provider.rejectionRate)}% (${provider.duplicate + provider.too_long}/${provider.candidates})`);
  appendCell(row, provider.detailed ? `${provider.exhausted}` : "Not measured");
  appendCell(row, provider.errorRate == null ? "--" : `${percentageFormat.format(provider.errorRate)}% (${provider.network_error + provider.provider_error}/${provider.fetches})`);
  const reasons = Object.fromEntries(["duplicate", "too_long", "network_error", "provider_error"].map((reason) => [reason, provider[reason]]));
  appendCell(row, provider.detailed ? rejectionSummary(reasons) : "Historical detail unavailable");
  appendCell(row, historyComparison(provider.rejectionRate, prior?.rejectionRate, true));
}

function renderProviderSupply(daily, options) {
  const view = historicalViews.operations;
  const current = DashboardHistory.providerSupply(view.data, view.period);
  const prior = DashboardHistory.providerSupply(view.data, DashboardHistory.previous(view.period));
  setText("provider-supply-coverage", `${current.measuredRuns}/${current.postingAttempts} archived posting attempts have publication outcomes; ${current.detailedRuns} have per-provider candidate detail. ${current.published} publications; ${current.failedPublications} unsuccessful publication attempts. Manual runs and retries count as separate attempts, not scheduled slots. Missing archive/log observations are not zeroes.`);
  setText("provider-leading-source", current.leadingSource ? displayName(current.leadingSource) : "--");
  setText("provider-leading-share", current.leadingShare == null ? "--" : `${percentageFormat.format(current.leadingShare)}%`);
  setText("provider-leading-change", historyComparison(current.leadingShare, prior.leadingShare, true));
  setText("provider-concentration", current.concentration == null ? "--" : numberFormat.format(current.concentration));
  setText("provider-publication-change", `All-source publications: ${historyComparison(current.measuredRuns ? current.published : null, prior.measuredRuns ? prior.published : null)}`);
  const body = document.querySelector("#provider-supply-table tbody");
  body.replaceChildren();
  current.providers.forEach((provider) => {
    const row = document.createElement("tr");
    providerSupplyCells(row, provider, prior.providers.find((item) => item.name === provider.name));
    body.append(row);
  });
  document.getElementById("provider-supply-empty").hidden = current.providers.length > 0;
  replaceChart("providerConcentration", document.getElementById("provider-concentration-chart"), {
    type: "line",
    data: {
      labels: daily.map((item) => item.date),
      datasets: [
        { label: "Largest source's daily publication share", data: daily.map((item) => item.providerLeadingShare), borderColor: colours[2], spanGaps: false },
        { label: "Daily concentration index × 100", data: daily.map((item) => item.providerConcentration == null ? null : item.providerConcentration * 100), borderColor: colours[3], spanGaps: false },
      ],
    },
    options,
  });
  replaceChart("providerRejections", document.getElementById("provider-rejections-chart"), {
    type: "line",
    data: {
      labels: daily.map((item) => item.date),
      datasets: current.providers.filter((provider) => provider.detailed).map((provider, index) => ({
        label: `${displayName(provider.name)} content rejection`,
        data: daily.map((item) => item.providerRejectionRates[provider.name] ?? null),
        borderColor: colours[index % colours.length],
        spanGaps: false,
      })),
    },
    options,
  });
}

async function updateHistoricalView(viewName, selection, custom = {}) {
  const view = historicalViews[viewName];
  const revision = ++view.revision;
  const status = document.getElementById(`${viewName}-history-status`);
  status.hidden = false;
  status.textContent = "Loading selected and comparison history...";
  try {
    const index = await readHistoryJson("data/history/index.json");
    const earliest = index.months?.map((month) => month.first_timestamp).filter(Boolean).sort()[0];
    if (selection === "all" && !earliest) throw new Error("No archived history is available.");
    const period = DashboardHistory.range(selection, metrics.generated_at, custom, earliest);
    const partitions = viewName === "operations"
      ? await DashboardHistory.loadPartitions(index, period, readHistoryJson)
      : [];
    const daily = viewName === "audience" ? await readHistoryJson("data/history/daily.json") : null;
    const data = DashboardHistory.merge(partitions, metrics, daily);
    if (revision !== view.revision) return;
    Object.assign(view, { selection, period, data });
    const attribute = viewName === "audience" ? "range" : "operationsRange";
    const selector = viewName === "audience" ? "[data-range]" : "[data-operations-range]";
    document.querySelectorAll(selector).forEach((button) => {
      const selected = button.dataset[attribute] === selection;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    renderHistorySummary(viewName);
    if (viewName === "audience") {
      renderAudienceChart();
      renderActivityChart();
      const dailySeries = DashboardHistory.series(data, period);
      replaceChart("engagementHistory", document.getElementById("engagement-history-chart"), {
        type: "line",
        data: {
          labels: dailySeries.map((item) => item.date),
          datasets: [{
            label: "Visible retained joke interactions",
            data: dailySeries.map((item) => item.engagement_total),
            borderColor: colours[0],
            spanGaps: false,
          }],
        },
        options: baseOptions(),
      });
    } else {
      renderOperationalHistory();
    }
    status.hidden = true;
  } catch (error) {
    if (revision !== view.revision) return;
    console.error(error);
    historyRequests.clear();
    status.textContent = `${error.message} Previous charts remain unchanged. Select the period again to retry.`;
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
    ["bluesky_snapshot", "bluesky_daily", "missing"].includes(item.source),
  );
  const chartFrame = document.getElementById("audience-chart-frame");
  const chartCanvas = document.getElementById("audience-chart");
  const emptyState = document.getElementById("audience-empty");
  const measured = snapshots.filter((item) => item.followers != null);
  const hasHistory = measured.length >= 2;
  chartCanvas.hidden = !hasHistory;
  emptyState.hidden = hasHistory;
  chartFrame.classList.toggle("is-empty", !hasHistory);

  if (!hasHistory) {
    charts.audience?.destroy();
    delete charts.audience;
  } else {
    const baseline = measured[0];
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
            data: snapshots.map((item) => item.followers == null ? null : item.followers - baseline.followers),
            absoluteValues: snapshots.map((item) => item.followers),
            borderColor: colours[0],
            backgroundColor: colours[0],
            tension: 0.25,
          },
          {
            label: "Following",
            data: snapshots.map((item) => item.following == null ? null : item.following - baseline.following),
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
          : item.source === "missing" ? "No sample" : "Reconstructed",
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
        { label: "Follows", data: activity.map((item) => item.follows ?? null), backgroundColor: colours[2] },
        { label: "Unfollows", data: activity.map((item) => item.unfollows), backgroundColor: colours[1] },
      ],
    },
    options,
  });
  renderTable(
    "activity-table",
    activity.map((item) => [item.date, metricText(item.joke_posts), metricText(item.follows), metricText(item.unfollows)]),
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

function checkpointText(summary) {
  const pending = summary.pending ? ` · ${numberFormat.format(summary.pending)} due` : "";
  if (summary.rate === null) return `Not yet observed${pending}`;
  return `${numberFormat.format(summary.stillFollowing)}/${numberFormat.format(summary.observed)} observed (${percentageFormat.format(summary.rate)}%)${pending}`;
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
    observed30
      ? `${numberFormat.format(retained30)}/${numberFormat.format(observed30)} observed accounts following us`
      : "No day-30 observations yet",
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
    let context = values.considered === undefined
      ? "Collecting activity"
      : `${numberFormat.format(values.considered)} ${denominatorLabels[values.denominator] || "accounts"}`;
    if (
      source === "interaction" &&
      metrics.social_activity?.completed_runs > 0 &&
      Number.isFinite(metrics.social_activity.interaction_candidates)
    ) {
      context = `${numberFormat.format(metrics.social_activity.interaction_candidates)} candidates; ${context}`;
    }
    setText(
      `growth-${source}-context`,
      context,
    );
    setText(
      `growth-${source}-success`,
      values.success_rate === null || values.success_rate === undefined
        ? "--"
        : `${numberFormat.format(values.acquired)}/${numberFormat.format(values.considered)} (${percentageFormat.format(values.success_rate)}%)`,
    );
    [["30", checkpoint30], ["90", checkpoint90]].forEach(([checkpoint, summary]) => {
      setText(
        `growth-${source}-${checkpoint}`,
        checkpointText(summary),
      );
    });
  });

  renderTable(
    "growth-cohort-table",
    periods.map((period) => [
      period.month,
      period.source,
      numberFormat.format(period.acquired),
      checkpointText(checkpointSummary([period], period.source, "30")),
      checkpointText(checkpointSummary([period], period.source, "90")),
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
  setText(
    "response-window-duration",
    responseWindow?.days == null
      ? "Duration unavailable"
      : `${numberFormat.format(responseWindow.days)}-day protection`,
  );
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
    fallback: "Static fallback",
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
    (provider) => provider.configured !== false && typeof provider.healthy === "boolean",
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
    if (Number.isFinite(provider.last_health_check_at)) {
      badge.title = `Availability observed ${dateTimeFormat.format(new Date(provider.last_health_check_at * 1000))}`;
    }
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
  setText("production-delivery", sevenDays ? `${sevenDays.delivered}/${sevenDays.expected}` : "--");
  setText("production-missed", metricText(sevenDays?.missed));
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
  if (alert.kind === "workflow_failure_streak") {
    return `${displayName(alert.workflow)} failed ${numberFormat.format(alert.count)} consecutive completed runs; check the workflow logs`;
  }
  if (alert.kind === "mutation_persistence_uncertain") {
    return `${displayName(alert.workflow)} run ${alert.run_id} failed after making changes; verify saved state against completed actions before retrying`;
  }
  if (alert.kind === "joke_request_checkpoint_stale") {
    return "Joke-request checking is overdue; check the Follows and likes workflow";
  }
  if (alert.kind === "provider_health") {
    return `${numberFormat.format(alert.count)} configured provider${alert.count === 1 ? " needs" : "s need"} attention`;
  }
  if (alert.kind === "posting_delivery") {
    return `${numberFormat.format(alert.count)} posting slot${alert.count === 1 ? "" : "s"} missed in 7 complete days`;
  }
  return `Unrecognised operational alert: ${alert.kind}; check the dashboard collector`;
}

function renderOperationalPulse(automation) {
  const alerts = [...(automation.alerts || [])];
  if (Date.now() - new Date(metrics.generated_at).getTime() > 8 * 60 * 60 * 1000) {
    alerts.unshift({ kind: "stale_dashboard", level: "attention" });
  }
  const pulse = document.getElementById("operational-pulse");
  pulse.replaceChildren();
  const ciNames = metrics.operations?.ci_workflows || [];
  const production = alerts.filter((alert) => !ciNames.includes(alert.workflow));
  const ci = alerts.filter((alert) => ciNames.includes(alert.workflow));
  if (!production.length) {
    const clear = document.createElement("p");
    clear.className = "pulse-clear";
    clear.textContent = "No production alerts in the latest observation";
    pulse.append(clear);
  } else {
    production.forEach((alert) => {
      const item = document.createElement("p");
      item.className = `pulse-alert ${alert.level || "attention"}`;
      item.textContent = operationalAlertText(alert);
      pulse.append(item);
    });
  }
  const ciPulse = document.getElementById("ci-pulse");
  ciPulse.replaceChildren();
  const note = document.createElement("p");
  note.textContent = ci.length ? ci.map(operationalAlertText).join(" · ") : "No current CI alerts. Passing CI does not prove that posting or social actions completed.";
  ciPulse.append(note);
  renderComponentFreshness();
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

function performancePeriod(period) {
  const end = new Date(`${period.end}T00:00:00Z`);
  end.setUTCDate(end.getUTCDate() - 1);
  const start = new Date(`${period.start}T00:00:00Z`);
  return `${dateFormat.format(start)} to ${dateFormat.format(end)}`;
}

function renderPerformanceGroups(checkpoint, minimum) {
  const body = document.querySelector("#performance-comparison-table tbody");
  body.replaceChildren();
  const groups = [
    ...checkpoint.providers.map((item) => ({ ...item, label: displayName(item.provider) })),
    ...checkpoint.publishing_hours.map((item) => ({ ...item, label: `${item.utc_hour} UTC publishing hour` })),
  ];
  groups.forEach((item) => {
    const row = document.createElement("tr");
    const ready = item.observed >= minimum;
    appendCell(row, item.label);
    appendCell(row, `${item.observed} observed / ${item.missed} missed`);
    appendCell(row, ready ? metricText(item.mean) : `Needs ${minimum} observations`);
    appendCell(row, ready ? metricText(item.median) : "--");
    appendCell(row, ready ? `${percentageFormat.format(item.zero_share)}%` : "--");
    body.append(row);
  });
}

function renderPerformancePosts(posts) {
  const container = document.getElementById("performance-posts");
  container.replaceChildren();
  document.getElementById("performance-posts-empty").hidden = posts.length > 0;
  posts.forEach((post) => {
    const article = document.createElement("article");
    article.className = "performance-post";
    const text = document.createElement("p");
    text.textContent = post.text;
    const observation = document.createElement("p");
    // Do not round a near-deadline observation up to the excluded boundary.
    const age = Math.floor(post.age_hours * 100) / 100;
    observation.textContent = `${numberFormat.format(Object.values(post.engagement).reduce((sum, value) => sum + value, 0))} interactions observed at ${numberFormat.format(age)} hours old (${dateTimeFormat.format(new Date(post.observed_at))}).`;
    const link = document.createElement("a");
    link.href = `https://bsky.app/profile/${encodeURIComponent(metrics.account.handle)}/post/${encodeURIComponent(post.uri.split("/").at(-1))}`;
    link.textContent = "View public joke on Bluesky";
    article.append(text, observation, link);
    container.append(article);
  });
}

function renderJokePerformance() {
  const performance = metrics.joke_performance;
  const checkpoint = performance?.checkpoints?.[selectedPerformanceAge];
  document.getElementById("performance-content").hidden = !checkpoint;
  if (!checkpoint) {
    setText("performance-coverage", "Collecting comparable-age history. Earlier checkpoint counts cannot be reconstructed.");
    return;
  }
  const current = checkpoint.periods.recent;
  const previous = checkpoint.periods.previous;
  const band = checkpoint.window_hours.join("–");
  const coverage = checkpoint.coverage;
  setText("performance-coverage", `Tracking since ${dateTimeFormat.format(new Date(performance.coverage_started_at))}. ${coverage.observed} observations; ${coverage.missed} missed; ${coverage.pending} pending; ${coverage.before_coverage} checkpoints predate tracking. Receipts retained for ${performance.retention_days} days.`);
  setText("performance-period", `Publishing cohorts: ${performancePeriod(current)} compared with ${performancePeriod(previous)}. Each period is 30 complete UTC publishing days whose ${band}-hour windows have closed.`);
  setText("performance-samples", `${current.observed} / ${current.observed + current.missed}`);
  setText("performance-sample-note", `${current.missed} missed; ${current.before_coverage} before tracking. Previous period: ${previous.observed} observations, ${previous.missed} missed.`);
  setText("performance-mean", metricText(current.mean));
  setText("performance-median", metricText(current.median));
  setText("performance-zero", current.zero_share == null ? "--" : `${percentageFormat.format(current.zero_share)}%`);
  setText("performance-mean-change", historyComparison(current.mean, previous.mean));
  setText("performance-median-change", historyComparison(current.median, previous.median));
  setText("performance-zero-change", historyComparison(current.zero_share, previous.zero_share, true));
  setText("performance-empty", current.observed ? `Observed sample only, not impressions or causal attribution. All counts below use ${band}-hour observations.` : `Collecting comparable-age history: no ${band}-hour observations in this mature publishing cohort. Missing observations are not zero interactions.`);
  setText("performance-breakdown", current.observed ? Object.entries(current.engagement).map(([name, count]) => `${name}: ${numberFormat.format(count)}`).join(" · ") : "Interaction breakdown unavailable until a checkpoint is observed.");
  setText("performance-comparison-note", `Same mature publishing cohort and age band. Descriptive only: providers and UTC publishing hours may have different audiences. Group averages require ${performance.comparison_min_posts} observed posts; missed observations may bias samples. Publishing hour is not an inferred scheduled slot.`);
  renderPerformanceGroups(checkpoint, performance.comparison_min_posts);
  renderPerformancePosts(checkpoint.top_posts);
  const months = checkpoint.months;
  replaceChart("jokePerformance", document.getElementById("performance-chart"), {
    type: "line",
    data: {
      labels: months.map((item) => `${item.month} (n=${item.observed})`),
      datasets: [
        { label: `Mean at ${band} hours`, data: months.map((item) => item.mean), borderColor: colours[0], spanGaps: false },
        { label: `Median at ${band} hours`, data: months.map((item) => item.median), borderColor: colours[1], spanGaps: false },
      ],
    },
    options: baseOptions(),
  });
}

function renderCharts() {
  renderAudienceChart();
  renderActivityChart();
  renderAudienceGrowth();
  renderSocialActivity();
  renderEngagement();
  renderJokePerformance();
}

function bindRangeControls() {
  document.getElementById("slot-exceptions-inspect").addEventListener("click", () => {
    document.getElementById("slot-exceptions-region").focus();
  });
  document.querySelectorAll("[data-range]").forEach((button) => {
    button.addEventListener("click", () => {
      selectHistoricalPeriod("audience", button.dataset.range);
    });
  });
  document.querySelectorAll("[data-operations-range]").forEach((button) => {
    button.addEventListener("click", () => {
      selectHistoricalPeriod("operations", button.dataset.operationsRange);
    });
  });
  ["audience", "operations"].forEach((viewName) => {
    const form = document.getElementById(`${viewName}-history-custom`);
    const start = document.getElementById(`${viewName}-history-start`);
    const end = document.getElementById(`${viewName}-history-end`);
    const lastComplete = new Date(`${metrics.generated_at.slice(0, 10)}T00:00:00Z`);
    lastComplete.setUTCDate(lastComplete.getUTCDate() - 1);
    start.max = end.max = lastComplete.toISOString().slice(0, 10);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      void updateHistoricalView(viewName, "custom", { start: start.value, end: end.value });
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
  document.querySelectorAll("[data-performance-age]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedPerformanceAge = button.dataset.performanceAge;
      document.querySelectorAll("[data-performance-age]").forEach((item) => {
        const selected = item === button;
        item.classList.toggle("active", selected);
        item.setAttribute("aria-pressed", String(selected));
      });
      renderJokePerformance();
    });
  });
}

function selectHistoricalPeriod(viewName, selection) {
  const form = document.getElementById(`${viewName}-history-custom`);
  form.hidden = selection !== "custom";
  if (selection === "custom") {
    document.getElementById(`${viewName}-history-start`).focus();
    return;
  }
  void updateHistoricalView(viewName, selection);
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
    void updateHistoricalView("audience", "30");
    if (dashboardViewFromHash() === "operations") void updateHistoricalView("operations", "30");
  } catch (error) {
    console.error(error);
    document.getElementById("page-error").hidden = false;
    setText("collection-time", "Statistics unavailable");
  }
}

void initialise();
