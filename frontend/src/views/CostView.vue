<template>
  <div class="cost-view">
    <PermissionBanner feature="cost_report" />
    <!-- Controls -->
    <div class="controls-bar">
      <div class="period-selector">
        <button
          v-for="d in periodOptions"
          :key="d.value"
          class="period-btn"
          :class="{ active: costStore.days === d.value }"
          @click="costStore.setDays(d.value)"
        >{{ d.label }}</button>
      </div>
    </div>

    <!-- CUR Status Banner -->
    <div v-if="curStatus && !curStatus.found" class="cur-banner">
      <div class="cur-banner-header">
        <div class="cur-banner-icon">
          <i class="pi pi-info-circle"></i>
        </div>
        <div class="cur-banner-text">
          <strong>Using Cost Explorer (limited detail)</strong>
          <p>Enable AWS Cost and Usage Reports (CUR) for resource-level cost data, hourly granularity, and detailed service breakdowns.</p>
        </div>
        <button class="btn-dismiss" @click="dismissCurBanner">
          <i class="pi pi-times"></i>
        </button>
      </div>
      <div class="cur-banner-body">
        <div v-if="!showCurSetup" class="cur-actions">
          <button class="btn btn-cur-primary" @click="showCurSetup = true">
            <i class="pi pi-cog"></i> Set Up CUR
          </button>
          <span class="cur-cli-hint">
            Or via CLI: <code>tag-manager cost setup detect</code>
          </span>
        </div>
        <div v-else class="cur-setup-panel">
          <div class="cur-setup-tabs">
            <button
              class="cur-tab"
              :class="{ active: curTab === 'auto' }"
              @click="curTab = 'auto'"
            >Auto-Detect</button>
            <button
              class="cur-tab"
              :class="{ active: curTab === 'deploy' }"
              @click="curTab = 'deploy'"
            >Deploy New</button>
            <button
              class="cur-tab"
              :class="{ active: curTab === 'manual' }"
              @click="curTab = 'manual'"
            >Use Existing</button>
            <button
              class="cur-tab"
              :class="{ active: curTab === 'cli' }"
              @click="curTab = 'cli'"
            >CLI Guide</button>
          </div>
          <div class="cur-tab-content">
            <div v-if="curTab === 'auto'" class="cur-tab-panel">
              <p>Scan your AWS account for an existing CUR report and Athena/Glue configuration.</p>
              <button class="btn btn-cur-primary" :disabled="curLoading" @click="detectCUR">
                {{ curLoading ? 'Detecting...' : 'Detect CUR' }}
              </button>
              <div v-if="curMessage" class="cur-message" :class="curMessageType">{{ curMessage }}</div>
            </div>
            <div v-if="curTab === 'deploy'" class="cur-tab-panel">
              <p>Deploy a new CUR report with S3 bucket, Glue crawler, and Athena integration via CloudFormation. Data will be available within ~24 hours.</p>
              <div class="cur-form">
                <div class="cur-field">
                  <label>Report Name</label>
                  <input v-model="deployReportName" class="cur-input" placeholder="tag-manager-cur" />
                </div>
                <div class="cur-field">
                  <label>S3 Bucket (optional)</label>
                  <input v-model="deployBucket" class="cur-input" placeholder="Auto-generated if empty" />
                </div>
              </div>
              <button class="btn btn-cur-primary" :disabled="curLoading" @click="deployCUR">
                {{ curLoading ? 'Deploying...' : 'Deploy CUR Infrastructure' }}
              </button>
              <div v-if="curMessage" class="cur-message" :class="curMessageType">{{ curMessage }}</div>
            </div>
            <div v-if="curTab === 'manual'" class="cur-tab-panel">
              <p>Connect to an existing CUR Athena table.</p>
              <div class="cur-form">
                <div class="cur-field">
                  <label>Athena Database</label>
                  <input v-model="manualDatabase" class="cur-input" placeholder="e.g. athenacurcfn_cur_report" />
                </div>
                <div class="cur-field">
                  <label>Athena Table</label>
                  <input v-model="manualTable" class="cur-input" placeholder="e.g. cur_report" />
                </div>
              </div>
              <button class="btn btn-cur-primary" :disabled="curLoading || !manualDatabase || !manualTable" @click="validateCUR">
                {{ curLoading ? 'Validating...' : 'Validate & Connect' }}
              </button>
              <div v-if="curMessage" class="cur-message" :class="curMessageType">{{ curMessage }}</div>
            </div>
            <div v-if="curTab === 'cli'" class="cur-tab-panel">
              <p>Set up CUR using the tag-manager CLI:</p>
              <div class="cur-cli-steps">
                <div class="cli-step"><span class="step-num">1</span><div><strong>Detect existing CUR</strong><code>tag-manager cost setup detect</code></div></div>
                <div class="cli-step"><span class="step-num">2</span><div><strong>Create new CUR (if none found)</strong><code>tag-manager cost setup create</code></div></div>
                <div class="cli-step"><span class="step-num">3</span><div><strong>Or configure manually</strong><code>tag-manager cost setup configure --database &lt;db&gt; --table &lt;tbl&gt;</code></div></div>
                <div class="cli-step"><span class="step-num">4</span><div><strong>Validate access</strong><code>tag-manager cost setup validate</code></div></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- CUR Pending Banner -->
    <div v-if="curStatus && curStatus.found && curStatus.status === 'pending'" class="cur-banner cur-banner-warn">
      <div class="cur-banner-header">
        <div class="cur-banner-icon"><i class="pi pi-clock"></i></div>
        <div class="cur-banner-text">
          <strong>CUR report is pending</strong>
          <p>Your CUR report has been configured but data is not yet available. This typically takes up to 24 hours after initial setup.</p>
        </div>
      </div>
    </div>

    <!-- Tab Bar -->
    <div class="tab-bar">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="period-btn"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key"
      >{{ tab.label }}</button>
    </div>

    <!-- Loading / Error (overview only) -->
    <template v-if="activeTab === 'overview'">
      <div v-if="costStore.loading" class="loading-state">Loading cost data...</div>
      <div v-else-if="costStore.error" class="error-state">
        <i class="pi pi-exclamation-circle"></i>
        {{ costStore.error }}
      </div>

      <template v-else-if="costStore.summary">
        <!-- KPI Cards -->
        <div class="cards-grid">
          <div class="stat-card stat-clickable" @click="drillTo('total')">
            <div class="stat-icon stat-icon-blue">
              <i class="pi pi-dollar"></i>
            </div>
            <div class="stat-body">
              <span class="stat-value">{{ fmt.formatCurrency(costStore.summary.total_cost) }}</span>
              <span class="stat-label">Total Cost ({{ costStore.days }}d)</span>
            </div>
          </div>
          <div class="stat-card stat-clickable" @click="drillTo('daily')">
            <div class="stat-icon stat-icon-green">
              <i class="pi pi-chart-line"></i>
            </div>
            <div class="stat-body">
              <span class="stat-value">{{ fmt.formatCurrency(dailyAvg) }}</span>
              <span class="stat-label">Daily Average</span>
            </div>
          </div>
          <div class="stat-card stat-clickable" @click="drillTo('service', topServiceName)">
            <div class="stat-icon stat-icon-yellow">
              <i class="pi pi-chart-bar"></i>
            </div>
            <div class="stat-body">
              <span class="stat-value">{{ topServiceName }}</span>
              <span class="stat-label">Top Service</span>
            </div>
          </div>
          <div class="stat-card">
            <div class="stat-icon stat-icon-purple">
              <i class="pi pi-database"></i>
            </div>
            <div class="stat-body">
              <span class="stat-value">{{ costStore.summary.source }}</span>
              <span class="stat-label">Data Source</span>
            </div>
          </div>
        </div>

        <!-- Charts -->
        <div class="charts-grid">
          <div class="chart-card clickable-chart">
            <h3 class="chart-title">Cost by Service</h3>
            <VChart v-if="serviceChartOption" class="chart" :option="serviceChartOption" autoresize @click="onServiceChartClick" />
            <div v-else class="chart-empty">No data available</div>
          </div>
          <div class="chart-card clickable-chart">
            <h3 class="chart-title">Cost by Account</h3>
            <VChart v-if="accountChartOption" class="chart" :option="accountChartOption" autoresize @click="onAccountChartClick" />
            <div v-else class="chart-empty">No data available</div>
          </div>
        </div>

        <!-- Drill-Down Detail Panel -->
        <div v-if="drillDown.active" class="drilldown-card">
          <div class="drilldown-header">
            <h2 class="drilldown-title">
              <i class="pi pi-arrow-down"></i>
              {{ drillDown.title }}
            </h2>
            <button class="btn-dismiss" @click="drillDown.active = false">
              <i class="pi pi-times"></i>
            </button>
          </div>
          <div class="drilldown-content">
            <!-- Service detail -->
            <div v-if="drillDown.type === 'service'" class="drilldown-table-wrap">
              <table class="drilldown-table">
                <thead>
                  <tr>
                    <th>Service</th>
                    <th style="text-align:right">Cost</th>
                    <th style="text-align:right">% of Total</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="item in serviceBreakdown"
                    :key="item.name"
                    :class="{ 'row-highlight': item.name === drillDown.filter }"
                  >
                    <td>
                      <a href="#" class="drill-link" @click.prevent="router.push({ path: '/resources', query: { service: item.name.toLowerCase() } })">
                        {{ item.name }}
                      </a>
                    </td>
                    <td style="text-align:right">{{ fmt.formatCurrency(item.value) }}</td>
                    <td style="text-align:right">{{ ((item.value / costStore.summary!.total_cost) * 100).toFixed(1) }}%</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <!-- Account detail -->
            <div v-if="drillDown.type === 'account'" class="drilldown-table-wrap">
              <table class="drilldown-table">
                <thead>
                  <tr>
                    <th>Account ID</th>
                    <th style="text-align:right">Cost</th>
                    <th style="text-align:right">% of Total</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="item in accountBreakdown"
                    :key="item.name"
                    :class="{ 'row-highlight': item.name === drillDown.filter }"
                  >
                    <td class="mono">{{ item.name }}</td>
                    <td style="text-align:right">{{ fmt.formatCurrency(item.value) }}</td>
                    <td style="text-align:right">{{ ((item.value / costStore.summary!.total_cost) * 100).toFixed(1) }}%</td>
                    <td>
                      <a href="#" class="drill-link" @click.prevent="router.push({ path: '/resources', query: { search: item.name } })">
                        View Resources
                      </a>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <!-- Daily breakdown -->
            <div v-if="drillDown.type === 'daily'" class="drilldown-daily">
              <div class="daily-stats">
                <div class="daily-stat">
                  <span class="daily-stat-label">Daily Average</span>
                  <span class="daily-stat-value">{{ fmt.formatCurrency(dailyAvg) }}</span>
                </div>
                <div class="daily-stat">
                  <span class="daily-stat-label">Total ({{ costStore.days }}d)</span>
                  <span class="daily-stat-value">{{ fmt.formatCurrency(costStore.summary!.total_cost) }}</span>
                </div>
                <div class="daily-stat">
                  <span class="daily-stat-label">Projected Monthly</span>
                  <span class="daily-stat-value">{{ fmt.formatCurrency(dailyAvg * 30) }}</span>
                </div>
              </div>
              <p class="daily-hint">For detailed daily cost breakdown with trends, use: <code>tag-manager cost daily</code></p>
            </div>
            <!-- Total overview -->
            <div v-if="drillDown.type === 'total'" class="drilldown-daily">
              <div class="daily-stats">
                <div class="daily-stat">
                  <span class="daily-stat-label">Period</span>
                  <span class="daily-stat-value">{{ costStore.days }} days</span>
                </div>
                <div class="daily-stat">
                  <span class="daily-stat-label">Total Cost</span>
                  <span class="daily-stat-value">{{ fmt.formatCurrency(costStore.summary!.total_cost) }}</span>
                </div>
                <div class="daily-stat">
                  <span class="daily-stat-label">Services</span>
                  <span class="daily-stat-value">{{ serviceBreakdown.length }}</span>
                </div>
                <div class="daily-stat">
                  <span class="daily-stat-label">Accounts</span>
                  <span class="daily-stat-value">{{ accountBreakdown.length }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Forecast -->
        <div v-if="costStore.forecast" class="section-card">
          <div class="section-header">
            <h2 class="section-title">30-Day Forecast</h2>
          </div>
          <div class="forecast-content">
            <div class="forecast-item">
              <span class="forecast-label">Projected Cost</span>
              <span class="forecast-value">{{ fmt.formatCurrency(costStore.forecast.projected_cost) }}</span>
            </div>
            <div class="forecast-item">
              <span class="forecast-label">Daily Average</span>
              <span class="forecast-value">{{ fmt.formatCurrency(costStore.forecast.daily_average) }}</span>
            </div>
            <div class="forecast-item">
              <span class="forecast-label">Method</span>
              <span class="forecast-value">{{ costStore.forecast.method }}</span>
            </div>
          </div>
        </div>
      </template>

      <!-- No data fallback -->
      <div v-else class="empty-state">
        <i class="pi pi-dollar"></i>
        <p>No cost data available. Ensure AWS credentials are configured with Cost Explorer access.</p>
      </div>
    </template>

    <!-- ========== Daily Tab ========== -->
    <template v-if="activeTab === 'daily'">
      <div v-if="costStore.sectionLoading" class="loading-state">Loading daily cost data...</div>
      <div v-else-if="costStore.sectionError" class="error-state">
        <i class="pi pi-exclamation-circle"></i>
        {{ costStore.sectionError }}
      </div>
      <template v-else-if="costStore.daily">
        <div class="chart-card">
          <h3 class="chart-title">Daily Cost Trend</h3>
          <VChart v-if="dailyChartOption" class="chart" :option="dailyChartOption" autoresize />
          <div v-else class="chart-empty">No daily data available</div>
        </div>
        <div v-if="costStore.daily.items.length" class="section-card">
          <div class="section-header">
            <h2 class="section-title">Daily Breakdown</h2>
          </div>
          <div class="drilldown-table-wrap" style="padding: 1rem 1.25rem;">
            <table class="drilldown-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th style="text-align:right">Cost</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(item, idx) in costStore.daily.items" :key="idx">
                  <td>{{ extractString(item, ['date', 'Date', 'TimePeriod']) }}</td>
                  <td style="text-align:right">{{ fmt.formatCurrency(extractNumber(item, ['total_cost', 'cost', 'unblended_cost', 'Cost', 'Amount'])) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
      <div v-else class="empty-state">
        <i class="pi pi-calendar"></i>
        <p>No daily cost data available.</p>
      </div>
    </template>

    <!-- ========== Regions Tab ========== -->
    <template v-if="activeTab === 'regions'">
      <div v-if="costStore.sectionLoading" class="loading-state">Loading region data...</div>
      <div v-else-if="isCurRequiredError(costStore.sectionError)" class="cur-required-banner">
        <i class="pi pi-info-circle"></i>
        This feature requires Cost and Usage Reports (CUR). Set up CUR in the Overview tab.
      </div>
      <div v-else-if="costStore.sectionError" class="error-state">
        <i class="pi pi-exclamation-circle"></i>
        {{ costStore.sectionError }}
      </div>
      <template v-else-if="costStore.regions">
        <div class="chart-card">
          <h3 class="chart-title">Cost by Region</h3>
          <VChart v-if="regionChartOption" class="chart" :option="regionChartOption" autoresize />
          <div v-else class="chart-empty">No region data available</div>
        </div>
        <div v-if="regionBreakdown.length" class="section-card">
          <div class="section-header">
            <h2 class="section-title">Region Breakdown</h2>
          </div>
          <div class="drilldown-table-wrap" style="padding: 1rem 1.25rem;">
            <table class="drilldown-table">
              <thead>
                <tr>
                  <th>Region</th>
                  <th style="text-align:right">Cost</th>
                  <th style="text-align:right">%</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in regionBreakdown" :key="r.name">
                  <td>{{ r.name }}</td>
                  <td style="text-align:right">{{ fmt.formatCurrency(r.value) }}</td>
                  <td style="text-align:right">{{ regionTotal > 0 ? ((r.value / regionTotal) * 100).toFixed(1) : '0.0' }}%</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
      <div v-else class="empty-state">
        <i class="pi pi-globe"></i>
        <p>No region cost data available.</p>
      </div>
    </template>

    <!-- ========== Resources Tab ========== -->
    <template v-if="activeTab === 'resources'">
      <div v-if="costStore.sectionLoading" class="loading-state">Loading top resources...</div>
      <div v-else-if="isCurRequiredError(costStore.sectionError)" class="cur-required-banner">
        <i class="pi pi-info-circle"></i>
        This feature requires Cost and Usage Reports (CUR). Set up CUR in the Overview tab.
      </div>
      <div v-else-if="costStore.sectionError" class="error-state">
        <i class="pi pi-exclamation-circle"></i>
        {{ costStore.sectionError }}
      </div>
      <template v-else-if="costStore.topResources && costStore.topResources.items.length">
        <div class="section-card">
          <div class="section-header">
            <h2 class="section-title">Top Resources by Cost</h2>
          </div>
          <div class="drilldown-table-wrap" style="padding: 1rem 1.25rem;">
            <table class="drilldown-table">
              <thead>
                <tr>
                  <th>Resource</th>
                  <th>Service</th>
                  <th>Region</th>
                  <th style="text-align:right">Cost</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(item, idx) in costStore.topResources.items" :key="idx">
                  <td class="mono" style="max-width: 300px; overflow: hidden; text-overflow: ellipsis;"><ResourceLink :arn="extractString(item, ['resource_id', 'resource', 'Resource', 'line_item_resource_id'])" :max-len="45" /></td>
                  <td>{{ extractString(item, ['service', 'Service', 'product_name']) }}</td>
                  <td>{{ extractString(item, ['region', 'Region', 'product_region']) }}</td>
                  <td style="text-align:right">{{ fmt.formatCurrency(extractNumber(item, ['cost', 'unblended_cost', 'Cost', 'Amount'])) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
      <div v-else class="empty-state">
        <i class="pi pi-server"></i>
        <p>No resource cost data available.</p>
      </div>
    </template>

    <!-- ========== Services Tab ========== -->
    <template v-if="activeTab === 'services'">
      <div class="services-controls">
        <div class="tab-bar">
          <button
            v-for="svc in serviceSubTabs"
            :key="svc.key"
            class="period-btn"
            :class="{ active: activeService === svc.key }"
            @click="activeService = svc.key"
          >{{ svc.label }}</button>
        </div>
        <div class="tab-bar">
          <button
            v-for="v in serviceViewsForActive"
            :key="v"
            class="period-btn"
            :class="{ active: activeServiceView === v }"
            @click="activeServiceView = v"
          >{{ v }}</button>
        </div>
      </div>
      <div v-if="costStore.sectionLoading" class="loading-state">Loading {{ activeService }} data...</div>
      <div v-else-if="isCurRequiredError(costStore.sectionError)" class="cur-required-banner">
        <i class="pi pi-info-circle"></i>
        This feature requires Cost and Usage Reports (CUR). Set up CUR in the Overview tab.
      </div>
      <div v-else-if="costStore.sectionError" class="error-state">
        <i class="pi pi-exclamation-circle"></i>
        {{ costStore.sectionError }}
      </div>
      <template v-else-if="costStore.serviceDeepDive && costStore.serviceDeepDive.items.length">
        <div class="section-card">
          <div class="section-header">
            <h2 class="section-title">{{ costStore.serviceDeepDive.service }} - {{ costStore.serviceDeepDive.view }}</h2>
          </div>
          <div class="drilldown-table-wrap" style="padding: 1rem 1.25rem;">
            <table class="drilldown-table">
              <thead>
                <tr>
                  <th v-for="col in serviceDeepDiveColumns" :key="col" :style="isNumericColumn(col) ? 'text-align:right' : ''">{{ formatColumnHeader(col) }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(item, idx) in costStore.serviceDeepDive.items" :key="idx">
                  <td v-for="col in serviceDeepDiveColumns" :key="col" :style="isNumericColumn(col) ? 'text-align:right' : ''">{{ formatCellValue(item, col) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
      <div v-else-if="!costStore.sectionLoading && !costStore.sectionError" class="empty-state">
        <i class="pi pi-th-large"></i>
        <p>No service data available for {{ activeService }} / {{ activeServiceView }}.</p>
      </div>
    </template>

    <!-- ========== Trends Tab ========== -->
    <template v-if="activeTab === 'trends'">
      <div class="section-card">
        <div class="section-header">
          <h2 class="section-title">Cost Trend Analysis</h2>
        </div>
        <div class="analytics-form">
          <div class="cur-field">
            <label>Tag Key (required)</label>
            <input v-model="trendsForm.tag_key" class="cur-input" placeholder="e.g. Environment, Team" />
          </div>
          <div class="cur-field">
            <label>Periods</label>
            <input v-model.number="trendsForm.periods" type="number" class="cur-input" min="1" max="24" />
          </div>
          <div class="cur-field">
            <label>Granularity</label>
            <select v-model="trendsForm.granularity" class="cur-input">
              <option value="MONTHLY">Monthly</option>
              <option value="WEEKLY">Weekly</option>
            </select>
          </div>
          <div class="cur-field" style="align-self: flex-end;">
            <button
              class="btn btn-cur-primary"
              :disabled="!trendsForm.tag_key || costStore.sectionLoading"
              @click="runTrends"
            >{{ costStore.sectionLoading ? 'Analyzing...' : 'Analyze' }}</button>
          </div>
        </div>
      </div>
      <div v-if="costStore.sectionLoading" class="loading-state">Running trend analysis...</div>
      <div v-else-if="costStore.sectionError" class="error-state">
        <i class="pi pi-exclamation-circle"></i>
        {{ costStore.sectionError }}
      </div>
      <template v-else-if="costStore.trends">
        <div v-if="costStore.trends.summary" class="cards-grid">
          <div v-for="(val, key) in costStore.trends.summary" :key="String(key)" class="stat-card">
            <div class="stat-body">
              <span class="stat-value">{{ formatSummaryValue(val) }}</span>
              <span class="stat-label">{{ formatSummaryKey(String(key)) }}</span>
            </div>
          </div>
        </div>
        <div v-if="trendsChartOption" class="chart-card">
          <h3 class="chart-title">Trend: {{ costStore.trends.tag_key }}</h3>
          <VChart class="chart" :option="trendsChartOption" autoresize />
        </div>
        <div v-if="costStore.trends.trends.length" class="section-card">
          <div class="section-header">
            <h2 class="section-title">Trend Data</h2>
          </div>
          <div class="drilldown-table-wrap" style="padding: 1rem 1.25rem;">
            <table class="drilldown-table">
              <thead>
                <tr>
                  <th v-for="col in genericColumns(costStore.trends.trends)" :key="col">{{ formatColumnHeader(col) }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(item, idx) in costStore.trends.trends" :key="idx">
                  <td v-for="col in genericColumns(costStore.trends.trends)" :key="col">{{ formatCellValue(item, col) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </template>

    <!-- ========== Anomalies Tab ========== -->
    <template v-if="activeTab === 'anomalies'">
      <div class="section-card">
        <div class="section-header">
          <h2 class="section-title">Cost Anomaly Detection</h2>
        </div>
        <div class="analytics-form">
          <div class="cur-field">
            <label>Tag Key (required)</label>
            <input v-model="anomaliesForm.tag_key" class="cur-input" placeholder="e.g. Environment, Team" />
          </div>
          <div class="cur-field">
            <label>% Threshold</label>
            <input v-model.number="anomaliesForm.percent_threshold" type="number" class="cur-input" min="1" />
          </div>
          <div class="cur-field">
            <label>$ Threshold</label>
            <input v-model.number="anomaliesForm.absolute_threshold" type="number" class="cur-input" min="0" />
          </div>
          <div class="cur-field" style="align-self: flex-end;">
            <button
              class="btn btn-cur-primary"
              :disabled="!anomaliesForm.tag_key || costStore.sectionLoading"
              @click="runAnomalies"
            >{{ costStore.sectionLoading ? 'Detecting...' : 'Detect' }}</button>
          </div>
        </div>
      </div>
      <div v-if="costStore.sectionLoading" class="loading-state">Running anomaly detection...</div>
      <div v-else-if="costStore.sectionError" class="error-state">
        <i class="pi pi-exclamation-circle"></i>
        {{ costStore.sectionError }}
      </div>
      <template v-else-if="costStore.anomalies">
        <div class="cards-grid">
          <div class="stat-card">
            <div class="stat-icon stat-icon-red">
              <i class="pi pi-exclamation-triangle"></i>
            </div>
            <div class="stat-body">
              <span class="stat-value">{{ costStore.anomalies.total_anomalies }}</span>
              <span class="stat-label">Anomalies Detected</span>
            </div>
          </div>
          <div class="stat-card">
            <div class="stat-icon stat-icon-blue">
              <i class="pi pi-tag"></i>
            </div>
            <div class="stat-body">
              <span class="stat-value">{{ costStore.anomalies.tag_key }}</span>
              <span class="stat-label">Tag Key Analyzed</span>
            </div>
          </div>
        </div>
        <div v-if="costStore.anomalies.anomalies.length" class="anomaly-list">
          <div v-for="(anomaly, idx) in costStore.anomalies.anomalies" :key="idx" class="anomaly-card">
            <div class="anomaly-header">
              <span class="anomaly-tag-value">{{ extractString(anomaly, ['tag_value', 'name', 'group']) }}</span>
              <span class="anomaly-badge" :class="anomalySeverityClass(anomaly)">
                {{ extractString(anomaly, ['severity', 'level']) || 'anomaly' }}
              </span>
            </div>
            <div class="anomaly-details">
              <div class="anomaly-detail">
                <span class="anomaly-detail-label">Current Cost</span>
                <span class="anomaly-detail-value">{{ fmt.formatCurrency(extractNumber(anomaly, ['current_cost', 'cost', 'amount'])) }}</span>
              </div>
              <div class="anomaly-detail">
                <span class="anomaly-detail-label">Expected Cost</span>
                <span class="anomaly-detail-value">{{ fmt.formatCurrency(extractNumber(anomaly, ['expected_cost', 'baseline', 'average'])) }}</span>
              </div>
              <div class="anomaly-detail">
                <span class="anomaly-detail-label">Change</span>
                <span class="anomaly-detail-value anomaly-change-value">{{ extractNumber(anomaly, ['percent_change', 'change_percent', 'pct_change']).toFixed(1) }}%</span>
              </div>
            </div>
          </div>
        </div>
      </template>
    </template>

    <!-- ========== Report (Chargeback) Tab ========== -->
    <template v-if="activeTab === 'report'">
      <div class="section-card">
        <div class="section-header">
          <h2 class="section-title">Chargeback Report</h2>
        </div>
        <div class="analytics-form">
          <div class="cur-field">
            <label>Tag Key (required)</label>
            <input v-model="reportForm.tag_key" class="cur-input" placeholder="e.g. CostCenter, Team" />
          </div>
          <div class="cur-field">
            <label>Start Date</label>
            <input v-model="reportForm.start_date" type="date" class="cur-input" />
          </div>
          <div class="cur-field">
            <label>End Date</label>
            <input v-model="reportForm.end_date" type="date" class="cur-input" />
          </div>
          <div class="cur-field">
            <label>Granularity</label>
            <select v-model="reportForm.granularity" class="cur-input">
              <option value="MONTHLY">Monthly</option>
              <option value="DAILY">Daily</option>
            </select>
          </div>
          <div class="cur-field">
            <label>Group By (optional)</label>
            <input v-model="reportForm.group_by" class="cur-input" placeholder="e.g. SERVICE" />
          </div>
          <div class="cur-field" style="align-self: flex-end;">
            <button
              class="btn btn-cur-primary"
              :disabled="!reportForm.tag_key || !reportForm.start_date || !reportForm.end_date || costStore.sectionLoading"
              @click="runChargeback"
            >{{ costStore.sectionLoading ? 'Generating...' : 'Generate' }}</button>
          </div>
        </div>
      </div>
      <div v-if="costStore.sectionLoading" class="loading-state">Generating chargeback report...</div>
      <div v-else-if="costStore.sectionError" class="error-state">
        <i class="pi pi-exclamation-circle"></i>
        {{ costStore.sectionError }}
      </div>
      <template v-else-if="costStore.chargebackReport">
        <div class="section-card">
          <div class="section-header">
            <h2 class="section-title">Report: {{ costStore.chargebackReport.tag_key }}</h2>
          </div>
          <div class="drilldown-table-wrap" style="padding: 1rem 1.25rem;">
            <template v-if="chargebackItems.length">
              <table class="drilldown-table">
                <thead>
                  <tr>
                    <th v-for="col in genericColumns(chargebackItems)" :key="col">{{ formatColumnHeader(col) }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(item, idx) in chargebackItems" :key="idx">
                    <td v-for="col in genericColumns(chargebackItems)" :key="col">{{ formatCellValue(item, col) }}</td>
                  </tr>
                </tbody>
              </table>
            </template>
            <div v-else class="chart-empty">
              <pre style="text-align: left; font-size: 0.8rem; white-space: pre-wrap;">{{ JSON.stringify(costStore.chargebackReport.report, null, 2) }}</pre>
            </div>
          </div>
        </div>
      </template>
    </template>

    <!-- ========== Gaps Tab ========== -->
    <template v-if="activeTab === 'gaps'">
      <div class="section-card">
        <div class="section-header">
          <h2 class="section-title">Tagging Gap Analysis</h2>
        </div>
        <div class="analytics-form">
          <div class="cur-field" style="min-width: 300px;">
            <label>Required Tags (comma-separated)</label>
            <input v-model="gapsForm.required_tags_str" class="cur-input" placeholder="e.g. Environment, Team, CostCenter" />
          </div>
          <div class="cur-field">
            <label>Days</label>
            <input v-model.number="gapsForm.days" type="number" class="cur-input" min="1" />
          </div>
          <div class="cur-field">
            <label>Min Cost ($)</label>
            <input v-model.number="gapsForm.min_cost" type="number" class="cur-input" min="0" step="0.01" />
          </div>
          <div class="cur-field" style="align-self: flex-end;">
            <label class="checkbox-label">
              <input v-model="gapsForm.show_roi" type="checkbox" />
              Show ROI
            </label>
          </div>
          <div class="cur-field" style="align-self: flex-end;">
            <button
              class="btn btn-cur-primary"
              :disabled="!gapsForm.required_tags_str.trim() || costStore.sectionLoading"
              @click="runGaps"
            >{{ costStore.sectionLoading ? 'Analyzing...' : 'Analyze' }}</button>
          </div>
        </div>
      </div>
      <div v-if="costStore.sectionLoading" class="loading-state">Running gap analysis...</div>
      <div v-else-if="costStore.sectionError" class="error-state">
        <i class="pi pi-exclamation-circle"></i>
        {{ costStore.sectionError }}
      </div>
      <template v-else-if="costStore.gaps">
        <div v-if="gapsSummaryCards.length" class="cards-grid">
          <div v-for="card in gapsSummaryCards" :key="card.label" class="stat-card">
            <div class="stat-body">
              <span class="stat-value">{{ card.value }}</span>
              <span class="stat-label">{{ card.label }}</span>
            </div>
          </div>
        </div>
        <div v-if="gapsItems.length" class="section-card">
          <div class="section-header">
            <h2 class="section-title">Gaps Detail</h2>
          </div>
          <div class="drilldown-table-wrap" style="padding: 1rem 1.25rem;">
            <table class="drilldown-table">
              <thead>
                <tr>
                  <th v-for="col in genericColumns(gapsItems)" :key="col">{{ formatColumnHeader(col) }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(item, idx) in gapsItems" :key="idx">
                  <td v-for="col in genericColumns(gapsItems)" :key="col">{{ formatCellValue(item, col) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div v-else class="section-card">
          <div class="drilldown-table-wrap" style="padding: 1rem 1.25rem;">
            <pre style="text-align: left; font-size: 0.8rem; white-space: pre-wrap;">{{ JSON.stringify(costStore.gaps.gaps, null, 2) }}</pre>
          </div>
        </div>
      </template>
    </template>

    <!-- ========== Commitments Tab ========== -->
    <template v-if="activeTab === 'commitments'">
      <div v-if="costStore.sectionLoading" class="loading-state">Loading commitments data...</div>
      <div v-else-if="isCurRequiredError(costStore.sectionError)" class="cur-required-banner">
        <i class="pi pi-info-circle"></i>
        This feature requires Cost and Usage Reports (CUR). Set up CUR in the Overview tab.
      </div>
      <div v-else-if="costStore.sectionError" class="error-state">
        <i class="pi pi-exclamation-circle"></i>
        {{ costStore.sectionError }}
      </div>
      <template v-else-if="costStore.savingsPlans || costStore.reservations">
        <div v-if="costStore.savingsPlans && costStore.savingsPlans.items.length" class="section-card">
          <div class="section-header">
            <h2 class="section-title">Savings Plans</h2>
          </div>
          <div class="drilldown-table-wrap" style="padding: 1rem 1.25rem;">
            <table class="drilldown-table">
              <thead>
                <tr>
                  <th v-for="col in genericColumns(costStore.savingsPlans.items)" :key="col">{{ formatColumnHeader(col) }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(item, idx) in costStore.savingsPlans.items" :key="idx">
                  <td v-for="col in genericColumns(costStore.savingsPlans.items)" :key="col">{{ formatCellValue(item, col) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div v-else class="empty-state">
          <p>No Savings Plans found.</p>
        </div>
        <div v-if="costStore.reservations && costStore.reservations.items.length" class="section-card">
          <div class="section-header">
            <h2 class="section-title">Reserved Instances</h2>
          </div>
          <div class="drilldown-table-wrap" style="padding: 1rem 1.25rem;">
            <table class="drilldown-table">
              <thead>
                <tr>
                  <th v-for="col in genericColumns(costStore.reservations.items)" :key="col">{{ formatColumnHeader(col) }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(item, idx) in costStore.reservations.items" :key="idx">
                  <td v-for="col in genericColumns(costStore.reservations.items)" :key="col">{{ formatCellValue(item, col) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div v-else class="empty-state">
          <p>No Reserved Instances found.</p>
        </div>
      </template>
      <div v-else class="empty-state">
        <i class="pi pi-wallet"></i>
        <p>No commitments data available.</p>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import PermissionBanner from '@/components/PermissionBanner.vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart, BarChart, LineChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { useCostStore } from '@/stores/cost'
import { useFormatters } from '@/composables/useFormatters'
import { api } from '@/api/client'
import type { CURStatusResponse } from '@/types/api'
import ResourceLink from '@/components/ResourceLink.vue'

use([CanvasRenderer, PieChart, BarChart, LineChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent])

const costStore = useCostStore()
const router = useRouter()
const fmt = useFormatters()

// ---- Tab state ----
type TabKey = 'overview' | 'daily' | 'regions' | 'resources' | 'services' | 'trends' | 'anomalies' | 'report' | 'gaps' | 'commitments'

const tabs: { key: TabKey; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'daily', label: 'Daily' },
  { key: 'regions', label: 'Regions' },
  { key: 'resources', label: 'Resources' },
  { key: 'services', label: 'Services' },
  { key: 'trends', label: 'Trends' },
  { key: 'anomalies', label: 'Anomalies' },
  { key: 'report', label: 'Report' },
  { key: 'gaps', label: 'Gaps' },
  { key: 'commitments', label: 'Commitments' },
]

const activeTab = ref<TabKey>('overview')

// ---- CUR setup state ----
const curStatus = ref<CURStatusResponse | null>(null)
const curLoading = ref(false)
const curMessage = ref('')
const curMessageType = ref<'success' | 'error' | 'info'>('info')
const showCurSetup = ref(false)
const curTab = ref<'auto' | 'deploy' | 'manual' | 'cli'>('auto')
const deployReportName = ref('tag-manager-cur')
const deployBucket = ref('')
const manualDatabase = ref('')
const manualTable = ref('')

// ---- Drill-down state ----
const drillDown = reactive({
  active: false,
  type: '' as '' | 'service' | 'account' | 'daily' | 'total',
  title: '',
  filter: '',
})

// ---- Services tab state ----
const serviceSubTabs = [
  { key: 'ec2', label: 'EC2' },
  { key: 's3', label: 'S3' },
  { key: 'rds', label: 'RDS' },
  { key: 'lambda', label: 'Lambda' },
]

const serviceViews: Record<string, string[]> = {
  ec2: ['summary', 'instances', 'families', 'pricing'],
  s3: ['summary', 'buckets', 'storage_classes'],
  rds: ['summary', 'instances', 'engines'],
  lambda: ['summary', 'functions', 'pricing'],
}

const activeService = ref('ec2')
const activeServiceView = ref('summary')

const serviceViewsForActive = computed(() => {
  return serviceViews[activeService.value] || ['summary']
})

// ---- Analytics form states ----
const trendsForm = reactive({
  tag_key: '',
  periods: 6,
  granularity: 'MONTHLY',
})

const anomaliesForm = reactive({
  tag_key: '',
  percent_threshold: 20,
  absolute_threshold: 100,
})

const reportForm = reactive({
  tag_key: '',
  start_date: '',
  end_date: '',
  granularity: 'MONTHLY',
  group_by: '',
})

const gapsForm = reactive({
  required_tags_str: '',
  days: 30,
  min_cost: 1.0,
  show_roi: false,
})

// ---- CUR helpers ----
function isCurRequiredError(err: string | null): boolean {
  if (!err) return false
  const lower = err.toLowerCase()
  return lower.includes('cur required') || lower.includes('402') || lower.includes('cost and usage report')
}

function dismissCurBanner(): void {
  curStatus.value = null
}

async function fetchCurStatus(): Promise<void> {
  try {
    curStatus.value = await api.curStatus()
  } catch {
    // Silently ignore - CUR detection is optional
  }
}

async function detectCUR(): Promise<void> {
  curLoading.value = true
  curMessage.value = ''
  try {
    const result = await api.curStatus()
    curStatus.value = result
    if (result.found) {
      curMessage.value = `CUR detected: ${result.report_name || result.athena_database} (${result.status})`
      curMessageType.value = 'success'
      if (result.status === 'active') {
        setTimeout(() => costStore.fetchAll(), 1000)
      }
    } else {
      curMessage.value = result.message || 'No CUR configuration found.'
      curMessageType.value = 'info'
    }
  } catch (e) {
    curMessage.value = e instanceof Error ? e.message : 'Detection failed'
    curMessageType.value = 'error'
  } finally {
    curLoading.value = false
  }
}

async function deployCUR(): Promise<void> {
  curLoading.value = true
  curMessage.value = ''
  try {
    const result = await api.curDeploy({
      report_name: deployReportName.value || 'tag-manager-cur',
      bucket_name: deployBucket.value || undefined,
    })
    if (result.success) {
      curMessage.value = `CUR deployment started. Data will be available in ~${result.estimated_ready_hours} hours.`
      curMessageType.value = 'success'
      await fetchCurStatus()
    } else {
      curMessage.value = result.message || 'Deployment failed'
      curMessageType.value = 'error'
    }
  } catch (e) {
    curMessage.value = e instanceof Error ? e.message : 'Deployment failed'
    curMessageType.value = 'error'
  } finally {
    curLoading.value = false
  }
}

async function validateCUR(): Promise<void> {
  curLoading.value = true
  curMessage.value = ''
  try {
    const result = await api.curValidate({
      database: manualDatabase.value,
      table: manualTable.value,
    })
    if (result.found) {
      curMessage.value = 'CUR configuration validated successfully!'
      curMessageType.value = 'success'
      curStatus.value = result
      setTimeout(() => costStore.fetchAll(), 1000)
    } else {
      curMessage.value = result.message || 'Validation failed'
      curMessageType.value = 'error'
    }
  } catch (e) {
    curMessage.value = e instanceof Error ? e.message : 'Validation failed'
    curMessageType.value = 'error'
  } finally {
    curLoading.value = false
  }
}

// ---- Period options ----
const periodOptions = [
  { label: '7 days', value: 7 },
  { label: '30 days', value: 30 },
  { label: '90 days', value: 90 },
]

// ---- Overview computed values ----
const dailyAvg = computed(() => {
  if (!costStore.summary) return 0
  return costStore.summary.total_cost / costStore.days
})

const serviceBreakdown = computed(() => {
  if (!costStore.byService?.items?.length) return []
  return costStore.byService.items.map((item) => {
    const rec = item as Record<string, unknown>
    const keys = rec.Keys as string[] | undefined
    const metrics = rec.Metrics as Record<string, Record<string, string>> | undefined
    return {
      name: (rec.service || rec.Service || keys?.[0] || 'Unknown') as string,
      value: Number(rec.cost || rec.unblended_cost || rec.Cost || metrics?.BlendedCost?.Amount || 0),
    }
  }).filter((d) => d.value > 0).sort((a, b) => b.value - a.value)
})

const accountBreakdown = computed(() => {
  if (!costStore.byAccount?.items?.length) return []
  return costStore.byAccount.items.map((item) => {
    const rec = item as Record<string, unknown>
    const keys = rec.Keys as string[] | undefined
    const metrics = rec.Metrics as Record<string, Record<string, string>> | undefined
    return {
      name: (rec.account_id || rec.AccountId || keys?.[0] || 'Unknown') as string,
      value: Number(rec.cost || rec.unblended_cost || rec.Cost || metrics?.BlendedCost?.Amount || 0),
    }
  }).filter((d) => d.value > 0).sort((a, b) => b.value - a.value)
})

const topServiceName = computed(() => {
  if (!serviceBreakdown.value.length) return '-'
  return serviceBreakdown.value[0].name
})

const serviceChartOption = computed(() => {
  if (!serviceBreakdown.value.length) return null
  const data = serviceBreakdown.value.slice(0, 10)
  return {
    tooltip: { trigger: 'item', formatter: '{b}: ${c} ({d}%)' },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      itemStyle: { borderRadius: 6, borderColor: 'var(--surface-card)', borderWidth: 2 },
      label: { show: true, formatter: '{b}', color: 'var(--text-color-secondary)' },
      emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.3)' } },
      data,
    }],
  }
})

const accountChartOption = computed(() => {
  if (!accountBreakdown.value.length) return null
  const data = accountBreakdown.value
  return {
    tooltip: { trigger: 'axis', formatter: (params: { name: string; value: number }[]) => {
      const p = Array.isArray(params) ? params[0] : params
      return `Account: ${(p as { name: string }).name}<br/>Cost: $${Number((p as { value: number }).value).toFixed(2)}`
    }},
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      data: data.map((d) => d.name),
      axisLabel: { fontSize: 10, rotate: 30, color: 'var(--text-color-secondary)' },
    },
    yAxis: { type: 'value', axisLabel: { formatter: '${value}', color: 'var(--text-color-secondary)' } },
    series: [{
      type: 'bar',
      data: data.map((d) => d.value),
      itemStyle: { borderRadius: [4, 4, 0, 0], color: '#5a9aff' },
      emphasis: { itemStyle: { color: '#7ab3ff' } },
    }],
  }
})

// ---- Daily tab chart ----
const dailyChartOption = computed(() => {
  if (!costStore.daily?.items?.length) return null
  const items = costStore.daily.items
  const dates = items.map((item) => extractString(item, ['date', 'Date', 'TimePeriod']))
  const costs = items.map((item) => extractNumber(item, ['total_cost', 'cost', 'unblended_cost', 'Cost', 'Amount']))

  // Check if items have by_service breakdown (Cost Explorer daily format)
  const hasServiceBreakdown = items.some((item) => (item as Record<string, unknown>).by_service)
  const serviceNames: string[] = []
  if (hasServiceBreakdown) {
    const nameSet = new Set<string>()
    for (const item of items) {
      const byService = (item as Record<string, unknown>).by_service as Record<string, number> | undefined
      if (byService) {
        for (const svc of Object.keys(byService)) nameSet.add(svc)
      }
    }
    serviceNames.push(...Array.from(nameSet).sort((a, b) => {
      // Sort by total cost descending
      const totalA = items.reduce((sum, it) => sum + (((it as Record<string, unknown>).by_service as Record<string, number>)?.[a] || 0), 0)
      const totalB = items.reduce((sum, it) => sum + (((it as Record<string, unknown>).by_service as Record<string, number>)?.[b] || 0), 0)
      return totalB - totalA
    }))
  }

  const series: Record<string, unknown>[] = hasServiceBreakdown && serviceNames.length > 0
    ? serviceNames.slice(0, 8).map((svc) => ({
        type: 'bar',
        name: svc,
        stack: 'cost',
        data: items.map((item) => (((item as Record<string, unknown>).by_service as Record<string, number>)?.[svc] || 0)),
        emphasis: { focus: 'series' },
      }))
    : [{
        type: 'line',
        data: costs,
        smooth: true,
        itemStyle: { color: '#5a9aff' },
        areaStyle: { color: 'rgba(32, 108, 245, 0.1)' },
      }]

  return {
    tooltip: {
      trigger: 'axis',
      ...(hasServiceBreakdown ? {
        formatter: (params: { seriesName: string; value: number; marker: string }[]) => {
          if (!Array.isArray(params) || !params.length) return ''
          const header = `<strong>${(params[0] as { axisValue?: string }).axisValue || ''}</strong><br/>`
          const lines = params.filter((p) => p.value > 0).map((p) =>
            `${p.marker} ${p.seriesName}: $${Number(p.value).toFixed(2)}`
          )
          const total = params.reduce((s, p) => s + Number(p.value), 0)
          return header + lines.join('<br/>') + `<br/><strong>Total: $${total.toFixed(2)}</strong>`
        },
      } : {
        formatter: (params: { name: string; value: number }[]) => {
          const p = Array.isArray(params) ? params[0] : params
          return `${(p as { name: string }).name}<br/>Cost: $${Number((p as { value: number }).value).toFixed(2)}`
        },
      }),
    },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    ...(hasServiceBreakdown && serviceNames.length > 0 ? {
      legend: {
        type: 'scroll',
        bottom: 0,
        textStyle: { color: 'var(--text-color-secondary)', fontSize: 10 },
      },
      grid: { left: '3%', right: '4%', bottom: '12%', containLabel: true },
    } : {}),
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { fontSize: 10, rotate: 30, color: 'var(--text-color-secondary)' },
    },
    yAxis: { type: 'value', axisLabel: { formatter: '${value}', color: 'var(--text-color-secondary)' } },
    series,
  }
})

// ---- Regions tab ----
const regionBreakdown = computed(() => {
  if (!costStore.regions?.items?.length) return []
  return costStore.regions.items.map((item) => {
    const rec = item as Record<string, unknown>
    return {
      name: (rec.region || rec.Region || rec.name || 'Unknown') as string,
      value: Number(rec.cost || rec.unblended_cost || rec.Cost || rec.amount || 0),
    }
  }).filter((d) => d.value > 0).sort((a, b) => b.value - a.value)
})

const regionTotal = computed(() => {
  return regionBreakdown.value.reduce((sum, r) => sum + r.value, 0)
})

const regionChartOption = computed(() => {
  if (!regionBreakdown.value.length) return null
  return {
    tooltip: { trigger: 'item', formatter: '{b}: ${c} ({d}%)' },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      itemStyle: { borderRadius: 6, borderColor: 'var(--surface-card)', borderWidth: 2 },
      label: { show: true, formatter: '{b}', color: 'var(--text-color-secondary)' },
      emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.3)' } },
      data: regionBreakdown.value,
    }],
  }
})

// ---- Services tab computed ----
const serviceDeepDiveColumns = computed(() => {
  if (!costStore.serviceDeepDive?.items?.length) return []
  return genericColumns(costStore.serviceDeepDive.items)
})

// ---- Trends tab chart ----
const trendsChartOption = computed(() => {
  if (!costStore.trends?.trends?.length) return null
  const items = costStore.trends.trends
  const labels = items.map((item) => extractString(item, ['period', 'date', 'month', 'week', 'label']))
  const values = items.map((item) => extractNumber(item, ['cost', 'unblended_cost', 'total_cost', 'amount', 'value']))
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { fontSize: 10, rotate: 30, color: 'var(--text-color-secondary)' },
    },
    yAxis: { type: 'value', axisLabel: { formatter: '${value}', color: 'var(--text-color-secondary)' } },
    series: [{
      type: 'line',
      data: values,
      smooth: true,
      itemStyle: { color: '#a78bfa' },
      areaStyle: { color: 'rgba(124, 58, 237, 0.12)' },
    }],
  }
})

// ---- Chargeback report computed ----
const chargebackItems = computed((): Record<string, unknown>[] => {
  if (!costStore.chargebackReport) return []
  const report = costStore.chargebackReport.report
  if (Array.isArray(report.items)) return report.items as Record<string, unknown>[]
  if (Array.isArray(report.rows)) return report.rows as Record<string, unknown>[]
  if (Array.isArray(report.data)) return report.data as Record<string, unknown>[]
  return []
})

// ---- Gaps computed ----
const gapsItems = computed((): Record<string, unknown>[] => {
  if (!costStore.gaps) return []
  const gaps = costStore.gaps.gaps
  if (Array.isArray(gaps)) return gaps as Record<string, unknown>[]
  const gapsObj = gaps as Record<string, unknown>
  if (Array.isArray(gapsObj.items)) return gapsObj.items as Record<string, unknown>[]
  if (Array.isArray(gapsObj.resources)) return gapsObj.resources as Record<string, unknown>[]
  if (Array.isArray(gapsObj.gaps)) return gapsObj.gaps as Record<string, unknown>[]
  return []
})

const gapsSummaryCards = computed(() => {
  if (!costStore.gaps) return []
  const gaps = costStore.gaps.gaps as Record<string, unknown>
  const cards: { label: string; value: string }[] = []
  if (gaps.total_untagged_cost !== undefined) {
    cards.push({ label: 'Untagged Cost', value: fmt.formatCurrency(Number(gaps.total_untagged_cost)) })
  }
  if (gaps.total_resources !== undefined) {
    cards.push({ label: 'Total Resources', value: String(gaps.total_resources) })
  }
  if (gaps.untagged_resources !== undefined) {
    cards.push({ label: 'Untagged Resources', value: String(gaps.untagged_resources) })
  }
  if (gaps.coverage_percent !== undefined) {
    cards.push({ label: 'Tag Coverage', value: `${Number(gaps.coverage_percent).toFixed(1)}%` })
  }
  if (gaps.potential_savings !== undefined) {
    cards.push({ label: 'Potential Savings', value: fmt.formatCurrency(Number(gaps.potential_savings)) })
  }
  return cards
})

// ---- Chart click handlers ----
function onServiceChartClick(params: { name?: string }): void {
  if (params.name) {
    drillDown.active = true
    drillDown.type = 'service'
    drillDown.title = `Cost Breakdown by Service`
    drillDown.filter = params.name
  }
}

function onAccountChartClick(params: { name?: string }): void {
  if (params.name) {
    drillDown.active = true
    drillDown.type = 'account'
    drillDown.title = `Cost Breakdown by Account`
    drillDown.filter = params.name
  }
}

function drillTo(type: 'service' | 'account' | 'daily' | 'total', filter = ''): void {
  drillDown.active = true
  drillDown.type = type
  drillDown.filter = filter
  switch (type) {
    case 'total':
      drillDown.title = 'Cost Overview'
      break
    case 'daily':
      drillDown.title = 'Daily Cost Breakdown'
      break
    case 'service':
      drillDown.title = filter ? `Service: ${filter}` : 'Cost by Service'
      break
    case 'account':
      drillDown.title = filter ? `Account: ${filter}` : 'Cost by Account'
      break
  }
}

// ---- Analytics action handlers ----
function runTrends(): void {
  costStore.fetchTrends({
    tag_key: trendsForm.tag_key,
    periods: trendsForm.periods,
    granularity: trendsForm.granularity,
  })
}

function runAnomalies(): void {
  costStore.fetchAnomalies({
    tag_key: anomaliesForm.tag_key,
    percent_threshold: anomaliesForm.percent_threshold,
    absolute_threshold: anomaliesForm.absolute_threshold,
  })
}

function runChargeback(): void {
  costStore.fetchChargeback({
    tag_key: reportForm.tag_key,
    start_date: reportForm.start_date,
    end_date: reportForm.end_date,
    granularity: reportForm.granularity || undefined,
    group_by: reportForm.group_by || undefined,
  })
}

function runGaps(): void {
  const tags = gapsForm.required_tags_str.split(',').map((t) => t.trim()).filter(Boolean)
  costStore.fetchGaps({
    required_tags: tags,
    days: gapsForm.days,
    min_cost: gapsForm.min_cost,
    show_roi: gapsForm.show_roi,
  })
}

// ---- Generic data helpers ----
function extractString(item: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    if (item[key] !== undefined && item[key] !== null) {
      return String(item[key])
    }
  }
  return '-'
}

function extractNumber(item: Record<string, unknown>, keys: string[]): number {
  for (const key of keys) {
    if (item[key] !== undefined && item[key] !== null) {
      return Number(item[key])
    }
  }
  return 0
}

function genericColumns(items: Record<string, unknown>[]): string[] {
  if (!items.length) return []
  const colSet = new Set<string>()
  for (const item of items) {
    for (const key of Object.keys(item)) {
      colSet.add(key)
    }
  }
  return Array.from(colSet)
}

function formatCellValue(item: Record<string, unknown>, col: string): string {
  const val = item[col]
  if (val === null || val === undefined) return '-'
  const num = typeof val === 'number' ? val : (typeof val === 'string' && val !== '' && !isNaN(Number(val)) ? Number(val) : null)
  if (num !== null) {
    const lower = col.toLowerCase()
    if (lower.includes('cost') || lower.includes('amount') || lower.includes('savings') || lower.includes('price')) {
      return fmt.formatCurrency(num)
    }
    if (lower.includes('percent') || lower.includes('pct') || lower.includes('change')) {
      return `${num.toFixed(1)}%`
    }
    if (lower.includes('count')) {
      return num.toLocaleString()
    }
    // For other numeric columns, format to 2 decimal places if fractional
    return num % 1 === 0 ? num.toLocaleString() : num.toFixed(2)
  }
  if (typeof val === 'object') return JSON.stringify(val)
  return String(val)
}

function formatColumnHeader(col: string): string {
  return col.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function isNumericColumn(col: string): boolean {
  const lower = col.toLowerCase()
  return lower.includes('cost') || lower.includes('amount') || lower.includes('price') || lower.includes('percent') || lower.includes('count') || lower.includes('savings')
}

function formatSummaryKey(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function formatSummaryValue(val: unknown): string {
  if (typeof val === 'number') {
    if (Math.abs(val) >= 1 && Math.abs(val) < 10000) return fmt.formatCurrency(val)
    return val.toLocaleString()
  }
  return String(val)
}

function anomalySeverityClass(anomaly: Record<string, unknown>): string {
  const severity = extractString(anomaly, ['severity', 'level']).toLowerCase()
  if (severity === 'high' || severity === 'critical') return 'severity-high'
  if (severity === 'medium') return 'severity-medium'
  return 'severity-low'
}

// ---- Tab watchers ----
watch(activeTab, (newTab) => {
  costStore.sectionError = null
  switch (newTab) {
    case 'daily':
      costStore.fetchDaily()
      break
    case 'regions':
      costStore.fetchRegions()
      break
    case 'resources':
      costStore.fetchTopResources()
      break
    case 'services':
      costStore.fetchServiceDeepDive(activeService.value, activeServiceView.value)
      break
    case 'commitments':
      costStore.fetchCommitments()
      break
  }
})

watch(activeService, (newService) => {
  activeServiceView.value = 'summary'
  if (activeTab.value === 'services') {
    costStore.fetchServiceDeepDive(newService, 'summary')
  }
})

watch(activeServiceView, (newView) => {
  if (activeTab.value === 'services') {
    costStore.fetchServiceDeepDive(activeService.value, newView)
  }
})

// ---- Lifecycle ----
onMounted(() => {
  costStore.fetchAll()
  costStore.fetchForecast()
  fetchCurStatus()
})
</script>

<style scoped>
.cost-view {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.controls-bar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
}

.period-selector {
  display: flex;
  gap: 0;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  overflow: hidden;
}

.period-btn {
  padding: 0.5rem 1rem;
  border: none;
  background: var(--surface-card);
  color: var(--text-color-secondary);
  font-size: 0.82rem;
  cursor: pointer;
  transition: all 0.15s;
  border-right: 1px solid var(--surface-border);
}

.period-btn:last-child { border-right: none; }

.period-btn.active {
  background: var(--gradient-brand-horizontal);
  color: white;
}

.period-btn:hover:not(.active) {
  background: var(--surface-ground);
}

.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 1rem;
}

.stat-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  padding: 1.25rem;
  display: flex;
  align-items: center;
  gap: 1rem;
}

.stat-clickable {
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.stat-clickable:hover {
  border-color: var(--primary-color);
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.08);
}

.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.1rem;
  flex-shrink: 0;
}

.stat-icon-blue { background: rgba(32, 108, 245, 0.12); color: #5a9aff; }
.stat-icon-green { background: rgba(34, 197, 94, 0.12); color: #4ade80; }
.stat-icon-yellow { background: rgba(234, 179, 8, 0.12); color: var(--color-warning); }
.stat-icon-purple { background: rgba(124, 58, 237, 0.12); color: #a78bfa; }
.stat-icon-red { background: rgba(239, 68, 68, 0.1); color: #f87171; }

.stat-body {
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-size: 1.2rem;
  font-weight: 700;
  color: var(--text-color);
}

.stat-label {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  margin-top: 2px;
}

.charts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
  gap: 1rem;
}

.chart-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  padding: 1.25rem;
}

.clickable-chart :deep(canvas) {
  cursor: pointer;
}

.chart-title {
  font-size: 0.9rem;
  font-weight: 600;
  margin-bottom: 1rem;
  background: var(--gradient-brand-horizontal);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.chart {
  height: 300px;
}

.chart-empty {
  height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-color-secondary);
  font-size: 0.875rem;
}

/* Drill-down panel */
.drilldown-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  overflow: hidden;
  animation: slideDown 0.2s ease-out;
}

@keyframes slideDown {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

.drilldown-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.85rem 1.25rem;
  border-bottom: 1px solid var(--surface-border);
  background: var(--surface-ground);
}

.drilldown-title {
  font-size: 0.9rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.drilldown-title i {
  font-size: 0.8rem;
  color: var(--primary-color);
}

.drilldown-content {
  padding: 1rem 1.25rem;
}

.drilldown-table-wrap {
  overflow-x: auto;
}

.drilldown-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.84rem;
}

.drilldown-table th {
  padding: 0.5rem 0.75rem;
  text-align: left;
  font-size: 0.76rem;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--text-color-secondary);
  border-bottom: 2px solid var(--surface-border);
}

.drilldown-table td {
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--surface-border);
}

.drilldown-table tbody tr:hover {
  background: rgba(32, 108, 245, 0.05);
}

.drilldown-table .row-highlight {
  background: rgba(32, 108, 245, 0.12);
}

.drilldown-table .mono {
  font-family: 'SF Mono', monospace;
  font-size: 0.8rem;
}

.drill-link {
  color: #5a9aff;
  text-decoration: none;
  font-size: 0.82rem;
}

.drill-link:hover {
  text-decoration: underline;
}

.drilldown-daily {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.daily-stats {
  display: flex;
  gap: 2.5rem;
  flex-wrap: wrap;
}

.daily-stat {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.daily-stat-label {
  font-size: 0.76rem;
  color: var(--text-color-secondary);
  text-transform: uppercase;
  font-weight: 500;
}

.daily-stat-value {
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--text-color);
}

.daily-hint {
  font-size: 0.8rem;
  color: var(--text-color-secondary);
}

.daily-hint code {
  background: var(--surface-ground);
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  font-family: 'SF Mono', monospace;
  font-size: 0.76rem;
}

/* Section / Forecast */
.section-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  overflow: hidden;
}

.section-header {
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--surface-border);
}

.section-title {
  font-size: 0.95rem;
  font-weight: 600;
  background: var(--gradient-brand-horizontal);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.forecast-content {
  display: flex;
  gap: 3rem;
  padding: 1.25rem;
}

.forecast-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.forecast-label {
  font-size: 0.78rem;
  color: var(--text-color-secondary);
}

.forecast-value {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-color);
}

.loading-state, .error-state, .empty-state {
  padding: 3rem;
  text-align: center;
  color: var(--text-color-secondary);
  font-size: 0.9rem;
}

.error-state { color: #f87171; }

.empty-state i {
  font-size: 2rem;
  display: block;
  margin-bottom: 1rem;
}

/* CUR Banner */
.cur-banner {
  background: var(--surface-card);
  border: 1px solid rgba(32, 108, 245, 0.25);
  border-left: 4px solid #5a9aff;
  border-radius: 10px;
  overflow: hidden;
}

.cur-banner-warn {
  border-color: rgba(234, 179, 8, 0.25);
  border-left-color: var(--color-warning);
}

.cur-banner-header {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
}

.cur-banner-icon {
  flex-shrink: 0;
  font-size: 1.1rem;
  color: #5a9aff;
  margin-top: 2px;
}

.cur-banner-warn .cur-banner-icon { color: var(--color-warning); }

.cur-banner-text { flex: 1; }

.cur-banner-text strong {
  font-size: 0.88rem;
  color: var(--text-color);
}

.cur-banner-text p {
  font-size: 0.82rem;
  color: var(--text-color-secondary);
  margin: 0.25rem 0 0;
  line-height: 1.5;
}

.btn-dismiss {
  background: none;
  border: none;
  color: var(--text-color-secondary);
  cursor: pointer;
  padding: 0.25rem;
  font-size: 0.85rem;
  opacity: 0.6;
  transition: opacity 0.15s;
}

.btn-dismiss:hover { opacity: 1; }

.cur-banner-body { padding: 0 1.25rem 1rem; }

.cur-actions {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.btn { padding: 0.5rem 1rem; border: none; border-radius: 6px; font-size: 0.85rem; cursor: pointer; font-weight: 500; }

.btn-cur-primary {
  padding: 0.45rem 1rem;
  border: none;
  border-radius: 6px;
  font-size: 0.82rem;
  font-weight: 500;
  cursor: pointer;
  background: var(--gradient-brand-horizontal);
  color: white;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  transition: all 0.2s;
}

.btn-cur-primary:hover { box-shadow: 0 0 14px rgba(32, 108, 245, 0.35); }
.btn-cur-primary:disabled { opacity: 0.6; cursor: not-allowed; }

.cur-cli-hint { font-size: 0.78rem; color: var(--text-color-secondary); }

.cur-cli-hint code {
  background: var(--surface-ground);
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  font-size: 0.76rem;
  font-family: 'SF Mono', monospace;
}

.cur-setup-panel {
  border-top: 1px solid var(--surface-border);
  padding-top: 0.75rem;
}

.cur-setup-tabs {
  display: flex;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 1rem;
  width: fit-content;
}

.cur-tab {
  padding: 0.4rem 0.85rem;
  border: none;
  background: var(--surface-card);
  color: var(--text-color-secondary);
  font-size: 0.78rem;
  cursor: pointer;
  transition: all 0.15s;
  border-right: 1px solid var(--surface-border);
}

.cur-tab:last-child { border-right: none; }
.cur-tab.active { background: var(--primary-color); color: white; }
.cur-tab:hover:not(.active) { background: var(--surface-ground); }

.cur-tab-panel p {
  font-size: 0.82rem;
  color: var(--text-color-secondary);
  margin: 0 0 0.75rem;
  line-height: 1.5;
}

.cur-form { display: flex; gap: 0.75rem; margin-bottom: 0.75rem; flex-wrap: wrap; }

.cur-field { display: flex; flex-direction: column; gap: 0.25rem; min-width: 240px; }
.cur-field label { font-size: 0.75rem; font-weight: 500; color: var(--text-color-secondary); }

.cur-input {
  padding: 0.45rem 0.65rem;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  font-size: 0.82rem;
  background: var(--surface-ground);
  color: var(--text-color);
  outline: none;
}

.cur-input:focus { border-color: var(--primary-color); }

.cur-message {
  margin-top: 0.75rem;
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  font-size: 0.8rem;
  line-height: 1.4;
}

.cur-message.success { background: rgba(34, 197, 94, 0.1); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.25); }
.cur-message.error { background: rgba(239, 68, 68, 0.1); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.25); }
.cur-message.info { background: rgba(32, 108, 245, 0.1); color: #5a9aff; border: 1px solid rgba(32, 108, 245, 0.25); }

.cur-cli-steps { display: flex; flex-direction: column; gap: 0.6rem; }

.cli-step { display: flex; align-items: flex-start; gap: 0.65rem; }

.step-num {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--primary-color);
  color: white;
  font-size: 0.72rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 1px;
}

.cli-step strong { display: block; font-size: 0.82rem; color: var(--text-color); margin-bottom: 0.2rem; }

.cli-step code {
  display: block;
  background: var(--surface-ground);
  padding: 0.3rem 0.55rem;
  border-radius: 4px;
  font-size: 0.76rem;
  font-family: 'SF Mono', monospace;
  color: var(--text-color-secondary);
}

/* Tab bar */
.tab-bar {
  display: flex;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  overflow: hidden;
  width: fit-content;
  flex-wrap: wrap;
}

/* Services controls */
.services-controls {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

/* Analytics form */
.analytics-form {
  display: flex;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  flex-wrap: wrap;
  align-items: flex-start;
}

/* CUR Required Banner */
.cur-required-banner {
  background: rgba(32, 108, 245, 0.1);
  border: 1px solid rgba(32, 108, 245, 0.25);
  border-left: 4px solid #5a9aff;
  border-radius: 8px;
  padding: 1rem 1.25rem;
  color: #5a9aff;
  font-size: 0.85rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

/* Anomaly cards */
.anomaly-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.anomaly-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  padding: 1rem 1.25rem;
}

.anomaly-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.75rem;
}

.anomaly-tag-value {
  font-weight: 600;
  font-size: 0.9rem;
  color: var(--text-color);
}

.anomaly-badge {
  padding: 0.2rem 0.6rem;
  border-radius: 12px;
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
}

.severity-high {
  background: rgba(239, 68, 68, 0.1);
  color: #f87171;
}

.severity-medium {
  background: rgba(234, 179, 8, 0.12);
  color: var(--color-warning);
}

.severity-low {
  background: rgba(34, 197, 94, 0.12);
  color: #4ade80;
}

.anomaly-details {
  display: flex;
  gap: 2rem;
  flex-wrap: wrap;
}

.anomaly-detail {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.anomaly-detail-label {
  font-size: 0.72rem;
  color: var(--text-color-secondary);
  text-transform: uppercase;
  font-weight: 500;
}

.anomaly-detail-value {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-color);
}

.anomaly-change-value {
  color: #f87171;
}

/* Checkbox label */
.checkbox-label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.82rem;
  color: var(--text-color);
  cursor: pointer;
  padding-top: 0.3rem;
}

.checkbox-label input[type="checkbox"] {
  width: 16px;
  height: 16px;
  cursor: pointer;
}
</style>
