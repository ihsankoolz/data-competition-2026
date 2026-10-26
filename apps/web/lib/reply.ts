/**
 * The reply to the sender of a new-record email: a fixed template, no AI. It asks only for the
 * details the read found missing and links to the form already filled in from the email.
 * Nothing here sends anything; the inbox shows it as a draft to copy.
 */

export type ReplyDraft = {
  greeting: string;
  /** The sentence before the list (or the whole ask when nothing is missing). */
  intro: string;
  /** Plain labels of the missing details, in the order the read listed them. */
  missing: string[];
  /** The sentence before the link. */
  ask: string;
  formUrl: string;
  signature: string;
};

/** "Grace Teo" -> "Grace". No name, or an empty one, gives null. */
export function firstName(fromName: string | null | undefined): string | null {
  const first = fromName?.trim().split(/\s+/)[0];
  return first ? first : null;
}

/** The pre-filled form for an email, as a full link the sender can open. */
export function formUrlFor(origin: string, emailId: string): string {
  return `${origin}/requests/new?email=${encodeURIComponent(emailId)}`;
}

export function buildReply({
  senderName,
  missingLabels,
  formUrl,
}: {
  senderName: string | null | undefined;
  missingLabels: string[];
  formUrl: string;
}): ReplyDraft {
  const name = firstName(senderName);
  const some = missingLabels.length > 0;
  return {
    greeting: name ? `Hi ${name},` : "Hello,",
    intro: some
      ? "Thanks for your email. We have started the request from it, but a few details are missing:"
      : "Thanks for your email. We have filled in the request form from it.",
    missing: missingLabels,
    ask: some
      ? "Please add them in the form below. Everything else is already filled in."
      : "Please check the details in the form below and submit it if they are right.",
    formUrl,
    signature: "MDM team",
  };
}

/** The draft as plain text, for the clipboard. */
export function replyText(draft: ReplyDraft): string {
  const parts = [
    draft.greeting,
    "",
    draft.intro,
    ...draft.missing.map((m) => `- ${m}`),
    "",
    draft.ask,
    draft.formUrl,
    "",
    draft.signature,
  ];
  return parts.join("\n");
}
