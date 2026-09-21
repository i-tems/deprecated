const INBOX_SYNC_EVENT = 'inbox:sync'

export function notifyInboxSync() {
  window.dispatchEvent(new Event(INBOX_SYNC_EVENT))
}
