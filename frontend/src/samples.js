// Sample transcripts for trying the assistant. Each one is a branch call that drives towards the
// "order a check" flow. Lines are `speaker: text`, the format the composer expects.

export const SAMPLES = [
  {
    id: 'roof',
    title: 'Roof repair, joint account',
    summary: 'Every input is said on the call. The record should resolve with nothing left to confirm.',
    lines: [
      ['advisor', 'Thanks for calling, Margaret. What can I do for you today?'],
      ['client', 'The roof people start Monday and I need a check for five thousand from the joint account.'],
      ['advisor', "Sure. That's the one ending 4471?"],
      ['client', 'Yes, that one.'],
      ['advisor', 'And who should it be made out to?'],
      ['client', 'Just make it out to me.'],
      ['advisor', "That's Margaret Hartley, correct?"],
      ['client', 'Yes.'],
      ['advisor', 'Where would you like it sent?'],
      ['client', 'Send it to the house, same as last time.'],
    ],
  },
  {
    id: 'tuition',
    title: 'Tuition deposit, large check',
    summary:
      'A twelve-thousand-dollar check, so the large-check verification applies. The call is cut short before the client says where to send it.',
    lines: [
      ['advisor', 'Good morning, Margaret. How are you?'],
      ['client', "Fine, thanks. Emma's tuition deposit is due at the end of the month, so I need a check for twelve thousand."],
      ['advisor', 'Of course. Which account should that come from?'],
      ['client', 'The joint account, the one David and I share.'],
      ['advisor', 'Ending 4471. And who should the check be made out to?'],
      ['client', 'Make it out to me, Margaret Hartley. I want to hand it over myself.'],
      ['advisor', 'Understood. And where would you like us to mail it?'],
      ['client', "Oh, hold on, someone's at the door. Can I call you right back?"],
      ['advisor', 'Of course. I will have everything ready when you call.'],
    ],
  },
]

export function transcriptText(sample) {
  return sample.lines.map(([speaker, text]) => `${speaker}: ${text}`).join('\n')
}
