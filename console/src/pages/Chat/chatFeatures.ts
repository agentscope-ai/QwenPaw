// Temporarily disabled: retain queue UI, submission logic, and stored items.
// Before restoring queues with manual steer, coordinate both submission paths
// to prevent duplicate sends and retain items when steer is not accepted.
export const MESSAGE_QUEUE_ENABLED = false;

// Only enable while busy: an idle Sender requires queue ownership to submit.
// Borrow the SDK's busy-submit entry without allocating a persistent queue.
// An undefined key falls back to the chat ID; an empty string disables it.
export const STEER_SUBMIT_QUEUE = {
  enable: true,
  getQueueKey: () => "",
  maxSize: 0,
};
