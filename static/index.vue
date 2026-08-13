<template id="page-fswatch">
  <div class="row q-col-gutter-md">
    <div class="col-12 col-md-8 q-gutter-y-md">
      <q-card>
        <q-card-section>
          <div class="row items-center no-wrap">
            <div class="col">
              <span class="text-h5">Funding Source Watch</span>
            </div>
            <div class="col-auto">
              <q-btn
                flat
                color="grey"
                icon="refresh"
                :loading="loading"
                @click="refresh"
              >
                <q-tooltip>Refresh</q-tooltip>
              </q-btn>
            </div>
          </div>

          <q-banner v-if="hasFallenBack" class="bg-red text-white q-mt-md">
            <template v-slot:avatar>
              <q-icon name="warning" />
            </template>
            LNbits is running on
            <strong>${ state.funding_source }</strong> while
            <strong>${ state.configured_funding_source }</strong> is configured.
          </q-banner>

          <div class="row q-mt-md q-col-gutter-md">
            <div class="col-12 col-sm-4">
              <div class="text-caption text-grey">Running on</div>
              <q-badge :color="hasFallenBack ? 'red' : 'green'" class="q-mt-xs">
                ${ state.funding_source || '...' }
              </q-badge>
            </div>
            <div class="col-12 col-sm-4">
              <div class="text-caption text-grey">Configured</div>
              <div class="q-mt-xs">
                ${ state.configured_funding_source || '...' }
              </div>
            </div>
            <div class="col-12 col-sm-4">
              <div class="text-caption text-grey">Status</div>
              <q-badge :color="state.healthy ? 'green' : 'red'" class="q-mt-xs">
                ${ state.healthy ? 'healthy' : 'unhealthy' }
              </q-badge>
            </div>
          </div>

          <div v-if="state.balance_msat !== null" class="q-mt-md">
            <div class="text-caption text-grey">Node balance</div>
            <div>${ formatSats(state.balance_msat) } sats</div>
          </div>

          <div v-if="state.error" class="q-mt-md text-red">
            ${ state.error }
          </div>
        </q-card-section>
      </q-card>

      <q-card>
        <q-card-section>
          <div class="row items-center no-wrap q-mb-md">
            <div class="col">
              <span class="text-h6">Events</span>
            </div>
            <div class="col-auto">
              <q-btn flat color="grey" icon="delete" @click="clearEvents">
                <q-tooltip>Clear log</q-tooltip>
              </q-btn>
            </div>
          </div>
          <q-table
            dense
            flat
            :rows="events"
            row-key="id"
            :columns="eventsTable.columns"
            v-model:pagination="eventsTable.pagination"
            :loading="eventsTable.loading"
            no-data-label="No events yet"
          >
            <template v-slot:body="props">
              <q-tr :props="props">
                <q-td key="created_at" :props="props">
                  ${ formatDate(props.row.created_at) }
                </q-td>
                <q-td key="event_type" :props="props">
                  <q-badge :color="eventColor(props.row.event_type)">
                    ${ props.row.event_type }
                  </q-badge>
                </q-td>
                <q-td key="funding_source" :props="props">
                  ${ props.row.previous_funding_source || '?' } &rarr; ${
                  props.row.funding_source }
                </q-td>
                <q-td key="webhook_status" :props="props">
                  ${ props.row.webhook_status }
                  <q-tooltip v-if="props.row.error">
                    ${ props.row.error }
                  </q-tooltip>
                </q-td>
              </q-tr>
            </template>
          </q-table>
        </q-card-section>
      </q-card>
    </div>

    <div class="col-12 col-md-4 q-gutter-y-md">
      <q-card>
        <q-card-section>
          <span class="text-h6">Settings</span>
          <q-form @submit="saveSettings" class="q-gutter-md q-mt-xs">
            <q-toggle v-model="settings.enabled" label="Watch enabled" />
            <q-input
              filled
              dense
              v-model="settings.webhook_url"
              type="url"
              label="Webhook URL"
              hint="POST with a JSON body on every change"
            />
            <q-input
              filled
              dense
              v-model="settings.webhook_secret"
              type="password"
              label="Webhook secret (optional)"
              hint="HMAC-SHA256 over the body, sent as X-LNbits-Signature"
            />
            <q-input
              filled
              dense
              v-model.number="settings.interval_seconds"
              type="number"
              min="10"
              max="3600"
              label="Check interval (seconds)"
            />
            <q-toggle
              v-model="settings.probe_status"
              label="Probe the backend"
            />
            <div class="text-caption text-grey q-mt-none">
              Also calls status() on the funding source, so an unreachable node
              is caught before it turns into a fallback.
            </div>
            <q-input
              filled
              dense
              v-model.number="settings.failure_threshold"
              type="number"
              min="1"
              max="20"
              label="Failed probes before alerting"
              :disable="!settings.probe_status"
            />
            <q-toggle
              v-model="settings.notify_admin"
              label="Also send LNbits admin notifications"
            />
            <div class="text-caption text-grey q-mt-none">
              Uses the Telegram / Nostr / email channels from the admin
              notification settings.
            </div>
            <div class="row q-gutter-sm">
              <q-btn unelevated color="primary" type="submit">Save</q-btn>
              <q-btn
                flat
                color="grey"
                :loading="testing"
                :disable="!settings.webhook_url"
                @click="testWebhook"
                >Test webhook</q-btn
              >
            </div>
          </q-form>
        </q-card-section>
      </q-card>

      <q-card>
        <q-card-section>
          <q-expansion-item group="extras" icon="info" label="Webhook payload">
            <q-card>
              <q-card-section>
                <pre class="text-caption">${ examplePayload }</pre>
              </q-card-section>
            </q-card>
          </q-expansion-item>
        </q-card-section>
      </q-card>
    </div>
  </div>
</template>
