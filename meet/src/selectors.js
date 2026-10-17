// Everything that depends on how Google Meet's page looks, in one place. Meet changes its page from time to time;
// when joining or listening stops working, this is the file to fix. Text patterns match Meet in English (the browser
// runs with --lang=en-US).

export const S = {
  // the "Ready to join?" screen, as a guest
  nameInput: ['input[aria-label="Your name"]', 'input[placeholder="Your name"]', 'input[aria-label*="name" i]'],
  joinButton: /^(ask to join|join now|join anyway|switch here)$/i,
  micOn: /turn on microphone/i,
  camOn: /turn on camera/i,
  dismiss: /^(got it|dismiss|close|no thanks|ok)$/i,

  // in the call
  leave: /leave call/i,
  captionsOn: /turn on captions/i,
  chatOpen: /chat with everyone/i,
  chatInput: ['textarea[aria-label="Send a message"]', 'textarea[aria-label*="message" i]', 'textarea'],

  // a link that isn't a meeting
  badCode: /(check your meeting code|invalid video call name|meeting code is invalid)/i,

  // how a join or a call ends
  refused: /(you can't join this (video )?call|denied your request|no one responded to your request|you can't join this meeting)/i,
  // which refusal it was: Google turning the request away (it never reaches the host), the host saying no, nobody answering
  blocked: /(you can't join this (video )?call|you can't join this meeting)/i,
  denied: /denied your request/i,
  unanswered: /no one responded to your request/i,
  ended: /(you left the meeting|the call has ended|you've been removed|you were removed|return to home screen|rejoin)/i,
};

// What the page itself reads (captions, chat, people): passed into the Meet tab.
export const PAGE = {
  captionsRegion: [
    'div[role="region"][aria-label*="aption" i]',
    '[aria-label="Captions"]',
  ],
  chatMessage: ['[data-message-id]'],
  chatSender: ['[data-sender-name]'],
  participantTile: ['[data-participant-id]', '[data-requested-participant-id]'],
};
