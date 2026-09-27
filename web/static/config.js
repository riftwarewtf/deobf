/* Page settings.

   This file is served to every visitor, so anything in it is public.

   discordWebhook reports each run (the script, the result, how it went) to a
   Discord channel. It is left empty on purpose: a webhook URL is a credential,
   and this repository is public, so committing one hands it to anyone who
   reads the page source or the repo - they can post to the channel and can
   delete the webhook. GitHub and Discord also revoke webhooks they find
   published.

   Three ways to switch it on, worst to best:

     1. Paste the URL below and push. Simplest, and public. Fine for a channel
        you do not mind strangers posting to; rotate it in Discord when it gets
        abused (Server Settings -> Integrations -> Webhooks).

     2. Serve the page from a copy of this file that is not committed
        (web/static/config.local.js is git-ignored; load it instead of this
        one). Keeps it out of the repository, still public to visitors.

     3. Run the deobfuscator as a server and set DEOB_DISCORD_WEBHOOK there
        (see web/README.md). The URL never leaves the machine, and the server
        reports the runs it handles. This is the only option where the webhook
        is not public. */
window.DeobfConfig = {
  discordWebhook: "https://discord.com/api/webhooks/1519337318111121418/mH8Av0dpNWnI970Wd8VfwMq_8k2KbC3J4sM9h_7kwBk9XDFY41iGhkNB_RUTtAjDdk0Q",

  /* Attach the script that went in and the Luau that came out. */
  attachInput: true,
  attachOutput: true,

  /* Discord takes 8 MB per request on an unboosted server; anything larger is
     attached truncated and the embed says so. */
  maxAttachmentBytes: 3 * 1024 * 1024,
  maxTotalAttachmentBytes: 6 * 1024 * 1024
};
