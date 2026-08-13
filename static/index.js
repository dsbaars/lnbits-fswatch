window.PageFswatch = {
  template: '#page-fswatch',
  delimiters: ['${', '}'],
  data: function () {
    return {
      loading: false,
      testing: false,
      state: {
        funding_source: '',
        configured_funding_source: '',
        healthy: true,
        error: null,
        balance_msat: null
      },
      settings: {
        enabled: false,
        webhook_url: '',
        webhook_secret: '',
        interval_seconds: 60,
        probe_status: true,
        failure_threshold: 2,
        notify_admin: false
      },
      events: [],
      eventsTable: {
        loading: false,
        columns: [
          {
            name: 'created_at',
            align: 'left',
            label: 'Time',
            field: 'created_at'
          },
          {
            name: 'event_type',
            align: 'left',
            label: 'Event',
            field: 'event_type'
          },
          {
            name: 'funding_source',
            align: 'left',
            label: 'Funding source',
            field: 'funding_source'
          },
          {
            name: 'webhook_status',
            align: 'left',
            label: 'Webhook',
            field: 'webhook_status'
          }
        ],
        pagination: {
          sortBy: 'created_at',
          descending: true,
          rowsPerPage: 10
        }
      },
      examplePayload: JSON.stringify(
        {
          event: 'funding_source_changed',
          timestamp: 1760000000,
          site_title: 'LNbits',
          lnbits_version: '1.5.6',
          funding_source: 'VoidWallet',
          previous_funding_source: 'LndRestWallet',
          configured_funding_source: 'LndRestWallet',
          healthy: true,
          error: null,
          balance_msat: null
        },
        null,
        2
      )
    }
  },
  computed: {
    hasFallenBack() {
      return (
        !!this.state.funding_source &&
        this.state.funding_source !== this.state.configured_funding_source
      )
    }
  },
  methods: {
    async refresh() {
      this.loading = true
      try {
        await Promise.all([this.getState(), this.getSettings(), this.getEvents()])
      } finally {
        this.loading = false
      }
    },
    async getState() {
      try {
        const {data} = await LNbits.api.request(
          'GET',
          '/fswatch/api/v1/state',
          null
        )
        this.state = data
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },
    async getSettings() {
      try {
        const {data} = await LNbits.api.request(
          'GET',
          '/fswatch/api/v1/settings',
          null
        )
        this.settings = data
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },
    async saveSettings() {
      try {
        const {data} = await LNbits.api.request(
          'PUT',
          '/fswatch/api/v1/settings',
          null,
          this.settings
        )
        this.settings = data
        Quasar.Notify.create({
          message: 'Settings saved.',
          color: 'positive'
        })
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },
    async testWebhook() {
      this.testing = true
      try {
        const {data} = await LNbits.api.request(
          'POST',
          '/fswatch/api/v1/test',
          null
        )
        const failed = String(data.webhook_status || '').startsWith('failed')
        Quasar.Notify.create({
          message: `Webhook responded: ${data.webhook_status}`,
          color: failed ? 'negative' : 'positive'
        })
        await this.getEvents()
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      } finally {
        this.testing = false
      }
    },
    async getEvents() {
      this.eventsTable.loading = true
      try {
        const {data} = await LNbits.api.request(
          'GET',
          '/fswatch/api/v1/events',
          null
        )
        this.events = data
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      } finally {
        this.eventsTable.loading = false
      }
    },
    clearEvents() {
      LNbits.utils
        .confirmDialog('Delete the whole event log?')
        .onOk(async () => {
          try {
            await LNbits.api.request('DELETE', '/fswatch/api/v1/events', null)
            await this.getEvents()
          } catch (error) {
            LNbits.utils.notifyApiError(error)
          }
        })
    },
    eventColor(eventType) {
      if (eventType === 'funding_source_healthy') return 'green'
      if (eventType === 'test') return 'grey'
      return 'red'
    },
    formatDate(value) {
      return LNbits.utils.formatDate(value)
    },
    formatSats(msat) {
      return LNbits.utils.formatSat(Math.floor((msat || 0) / 1000))
    }
  },
  async created() {
    await this.refresh()
  }
}
