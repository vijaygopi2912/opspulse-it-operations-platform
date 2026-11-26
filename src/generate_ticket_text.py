"""Add realistic, user-written ticket descriptions to the OPSPULSE incidents.

The original data only has short labels like "Network issue - VPN", which give
the answer away. Real tickets are written by employees in their own words:
casual, sometimes vague, with typos, urgency, and words that point to the
wrong category. This script writes one such description per incident so the
AI modules have something realistic to learn from.

Input : data/processed/incidents_clean.csv
Output: data/processed/tickets_with_text.csv
Run from the project root:  python src/generate_ticket_text.py
"""
import random
import re

import pandas as pd

SEED = 7
IN_FILE = "data/processed/incidents_clean.csv"
OUT_FILE = "data/processed/tickets_with_text.csv"

# The team each category *should* go to (same rule as generate_data.py)
CORRECT_GROUP = {
    "Network": "Network Team", "Hardware": "Desktop Support",
    "Software": "Application Support", "Access": "Service Desk",
    "Email": "Service Desk", "Security": "Security Operations",
}

# --------------------------------------------------------------------------
# What users actually write, per subcategory. {app}, {device} etc. are filled
# in randomly. Some templates deliberately use words from another category
# (e.g. a VPN problem that mentions a password), as real tickets do.
# --------------------------------------------------------------------------
SYMPTOMS = {
    "VPN": [
        "VPN keeps disconnecting every few minutes when I work from home",
        "can't connect to the VPN, it just says 'connecting' forever",
        "GlobalProtect shows gateway not reachable",
        "I'm on the VPN but can't reach any internal sites or shared drives",
        "VPN asks for my password again and again and then fails",  # sounds like Access
        "remote connection to the office network stopped working after the update",
    ],
    "Wi-Fi": [
        "wifi keeps dropping in the {place}",
        "my laptop can't see the office wireless network anymore",
        "connected to Wi-Fi but there is no internet",
        "the guest wifi in the {place} isn't working for our visitors",
        "wireless signal is very weak on the {floor} floor",
    ],
    "Switch outage": [
        "nobody on the {floor} floor has network, all the cables seem dead",
        "network points in the {place} stopped working",
        "whole row of desks lost connection at once",
        "the ethernet ports near my desk have no lights",
        "desk phones and PCs on our floor all went offline together",
    ],
    "Slow connection": [
        "internet is extremely slow today, pages take ages to load",
        "uploading files to SharePoint takes forever",
        "Teams calls keep freezing and the video is choppy",
        "network is really slow since this morning, everything lags",
        "file transfers to the shared drive are crawling",
    ],
    "Laptop": [
        "my laptop won't turn on, no lights at all",
        "laptop is overheating and shuts down by itself",
        "keyboard on my laptop has stopped working, some keys type wrong letters",
        "laptop screen is cracked after it fell",
        "my laptop is very slow and the fan is always loud",  # could be Software
        "battery drains in less than an hour",
    ],
    "Printer": [
        "the printer on the {floor} floor is jammed again",
        "can't print anything, jobs just sit in the queue",
        "printer says out of toner but we just replaced it",
        "prints come out with black lines across the page",
        "I can't find the {place} printer in my list of printers",
    ],
    "Monitor": [
        "my second monitor is not detected",
        "screen keeps flickering",
        "monitor shows 'no signal' even though the cable is connected",
        "there is a line of dead pixels on my display",
        "external screen goes black every few minutes",
    ],
    "Docking station": [
        "docking station doesn't charge my laptop anymore",
        "when I plug into the dock my monitors and keyboard don't work",
        "USB ports on the docking station stopped working",
        "laptop doesn't recognise the dock, need to restart every time",
    ],
    "Office 365": [
        "Excel keeps crashing when I open large files",
        "Word says my licence is not activated",
        "Teams won't open, just a white screen",
        "OneDrive is not syncing my files",
        "PowerPoint freezes whenever I add images",
        "Office keeps asking me to sign in",  # sounds like Access
    ],
    "ERP": [
        "can't post invoices in SAP, getting error {code}",
        "ERP system is very slow when running month-end reports",
        "purchase order screen in the ERP gives an error when saving",
        "SAP logs me out every few minutes",
        "the finance module shows wrong totals in the report",
    ],
    "Browser": [
        "Chrome keeps crashing on the HR portal",
        "Edge won't load the intranet page, says page can't be displayed",
        "browser shows a certificate error on an internal site",
        "pop-ups keep appearing in my browser",  # could be Security
        "the web portal doesn't work in Chrome but works in Edge",
    ],
    "Installation request": [
        "please install {software} on my laptop",
        "I need {software} installed for a project starting next week",
        "can you give me admin rights to install {software}",
        "need the latest version of {software}, mine is outdated",
        "request to install {software} for our new joiner",
    ],
    "Password reset": [
        "forgot my password, please reset it",
        "my password expired and I can't change it",
        "need a password reset for my {system} account",
        "the self-service password reset page isn't sending me the code",
        "changed my password yesterday and now nothing accepts it",
    ],
    "Account locked": [
        "my account is locked after too many attempts",
        "I'm locked out of my computer",
        "it says my account has been disabled",
        "locked out of {system} after the password change",
        "can't log in, it says account locked, please unlock",
    ],
    "New access request": [
        "please give me access to the {folder} shared folder",
        "new joiner in our team needs access to {system}",
        "I need read access to the {folder} SharePoint site",
        "requesting access to the {system} reporting module",
        "I moved to the {dept} team and need their drive access",
    ],
    "Outlook": [
        "Outlook is stuck on 'loading profile'",
        "emails are not arriving in my inbox since this morning",
        "Outlook keeps asking for my password",  # sounds like Access
        "my Outlook calendar is not showing meetings",
        "can't send emails, they stay in the outbox",
        "Outlook search doesn't find any emails",
    ],
    "Shared mailbox": [
        "I can't see the {dept} shared mailbox in Outlook anymore",
        "please add me to the {dept} team mailbox",
        "emails sent from the shared mailbox show my name instead",
        "shared mailbox is full and rejecting emails",
    ],
    "Spam": [
        "I'm receiving loads of spam emails every day",
        "important client emails are going to my junk folder",
        "getting a lot of newsletters I never signed up for",
        "spam filter blocked an email from our supplier",
    ],
    "Phishing": [
        "I got an email asking me to confirm my bank details, looks fake",
        "suspicious email pretending to be from the CEO asking for gift cards",
        "I clicked a link in a strange email and entered my password",  # Access words
        "received an email with an invoice attachment from someone I don't know",
        "email says my mailbox is full and to click a link, is this real?",  # Email words
    ],
    "Antivirus": [
        "antivirus popup says a threat was found on my laptop",
        "Defender says it's out of date and won't update",
        "my antivirus quarantined a file I need for work",
        "laptop very slow, antivirus scan running all the time",  # could be Hardware
    ],
    "Suspicious login": [
        "I got an alert about a sign-in from another country",
        "someone tried to log into my account from an unknown device",
        "received MFA prompts I didn't request",
        "my account sent emails I didn't write",  # Email words
        "login notification from a location I've never been to",
    ],
}

FILL = {
    "place": ["meeting room", "reception", "board room", "cafeteria", "training room", "Dubai office"],
    "floor": ["2nd", "3rd", "4th", "5th", "ground"],
    "code": ["F5 702", "M7 162", "KI 235", "error 500"],
    "software": ["Power BI Desktop", "Python", "Visual Studio Code", "Adobe Acrobat Pro", "Tableau", "Zoom"],
    "system": ["SAP", "ServiceNow", "HR portal", "payroll system", "CRM"],
    "folder": ["Finance", "Projects", "HR Policies", "Sales Reports", "Legal Contracts"],
    "dept": ["Finance", "HR", "Sales", "Operations", "Legal", "Marketing"],
}

OPENERS = ["", "", "", "Hi team, ", "Hello IT, ", "Hi, ", "Good morning, ", "Dear support, "]
WHEN = ["", "", " since this morning", " since yesterday", " after the update last night",
        " for the last two days", " again", " since I came back from leave"]

REQUEST_WORDS = ("please", "i need", "need", "request", "can you", "new joiner", "i moved")

# Users hint at urgency. Most hints match the real priority, some don't (people exaggerate).
URGENCY = {
    "P1": ["This is urgent, the whole department can't work.", "Customers are affected right now!",
           "URGENT - we have a client presentation in 30 minutes.", "Critical: production is down.",
           "The CEO needs this fixed immediately."],
    "P2": ["Several people in my team have the same problem.", "This is blocking my work today.",
           "I have a deadline this afternoon, please help quickly.", "Quite urgent please."],
    "P3": ["Please help.", "Can someone take a look?", "Thanks in advance.", ""],
    "P4": ["No rush, whenever someone has time.", "Low priority, just letting you know.",
           "Not urgent.", "Can be done next week."],
}
URGENCY_RATE = {"P1": 0.85, "P2": 0.65, "P3": 0.5, "P4": 0.6}
WRONG_URGENCY_RATE = 0.10  # e.g. a P4 ticket written as "URGENT"

# How support teams actually fixed each kind of problem (written in the resolution notes).
# Used by similar_tickets.py to suggest a fix for new tickets.
RESOLUTIONS = {
    "VPN": ["Reset the VPN profile and reinstalled the GlobalProtect client.", "Cleared cached VPN credentials and re-synced the account.", "Moved the user to a less busy VPN gateway."],
    "Wi-Fi": ["Re-joined the device to the corporate wireless profile.", "Restarted the access point serving the area.", "Updated the laptop's wireless driver."],
    "Switch outage": ["Replaced the failed switch module and restored the uplink.", "Power-cycled the floor switch after a firmware fault.", "Re-patched the cabinet after a loose uplink cable."],
    "Slow connection": ["Moved traffic off a saturated uplink to the backup link.", "Reset the network adapter and cleared the DNS cache.", "Applied QoS for Teams traffic on the site router."],
    "Laptop": ["Replaced the faulty battery under warranty.", "Gave the user a loaner and sent the laptop for repair.", "Cleaned the fan and updated the BIOS to stop overheating."],
    "Printer": ["Cleared the paper jam and replaced the worn roller.", "Restarted the print spooler and re-mapped the printer.", "Replaced the toner cartridge and recalibrated the printer."],
    "Monitor": ["Replaced the display cable.", "Updated the graphics driver and reset display settings.", "Replaced the faulty monitor."],
    "Docking station": ["Updated the docking station firmware.", "Replaced the docking station.", "Reinstalled the dock's USB drivers."],
    "Office 365": ["Repaired the Office installation and cleared its cache.", "Re-activated the Microsoft 365 licence.", "Reset the Teams and OneDrive clients and signed in again."],
    "ERP": ["Cleared the user's SAP session and reset their profile.", "Applied the vendor patch for the posting error.", "Rebuilt the report index to speed up month-end runs."],
    "Browser": ["Cleared the browser cache and reset its settings.", "Installed the internal root certificate.", "Added the portal to the browser compatibility list."],
    "Installation request": ["Installed the software from the company catalogue.", "Deployed the approved package through the software centre.", "Granted temporary admin rights for the installation."],
    "Password reset": ["Reset the password and confirmed MFA enrolment.", "Fixed self-service reset by updating the user's phone number.", "Synced the new password across all systems."],
    "Account locked": ["Unlocked the account; a phone was retrying an old password.", "Unlocked the account and reset the password.", "Re-enabled the account after HR confirmation."],
    "New access request": ["Granted access after manager approval.", "Added the user to the correct security group.", "Provisioned the role in the target system."],
    "Outlook": ["Rebuilt the Outlook profile.", "Repaired the mailbox data file.", "Cleared saved credentials and re-authenticated Outlook."],
    "Shared mailbox": ["Granted full access to the shared mailbox.", "Re-added the shared mailbox in Outlook.", "Archived old items to free mailbox space."],
    "Spam": ["Tuned the spam filter and blocked the sender domain.", "Added the supplier to the allow list.", "Blocked the bulk sender for the user."],
    "Phishing": ["Blocked the sender and removed the email from all mailboxes.", "Reset the password and checked sign-ins after the click.", "Confirmed with the security team that nothing was compromised."],
    "Antivirus": ["Updated antivirus definitions and ran a full scan.", "Restored the false-positive file and added an exclusion.", "Removed the detected malware and rescanned clean."],
    "Suspicious login": ["Revoked sessions, reset the password and enforced MFA.", "Confirmed the sign-in was legitimate travel.", "Blocked the IP address and reviewed mailbox rules."],
}

SIGN_OFFS = ["", "", "", " Thanks", " Thank you", " Regards, {name}", " Thanks, {name}", " Sent from my iPhone"]
NAMES = ["Ahmed", "Fatima", "Ravi", "Sarah", "Mohammed", "Anita", "James", "Layla", "Arjun", "Noura"]


def fill(text):
    return re.sub(r"\{(\w+)\}", lambda m: random.choice(FILL[m.group(1)]), text)


def add_typo(text):
    """Swap two neighbouring letters in one random word, as fast typists do."""
    words = text.split(" ")
    candidates = [i for i, w in enumerate(words) if len(w) > 4 and w.isalpha()]
    if not candidates:
        return text
    i = random.choice(candidates)
    w = words[i]
    j = random.randint(1, len(w) - 3)
    words[i] = w[:j] + w[j + 1] + w[j] + w[j + 2:]
    return " ".join(words)


def write_ticket(subcategory, priority):
    """Return (description, template_id). template_id records which sentence pattern was used,
    so the AI test can check tickets written in patterns the model has never seen."""
    idx = random.randrange(len(SYMPTOMS[subcategory]))
    symptom = fill(SYMPTOMS[subcategory][idx])
    is_request = symptom.lower().startswith(REQUEST_WORDS)
    when = "" if is_request else random.choice(WHEN)  # "since this morning" only fits problems
    text = random.choice(OPENERS) + symptom + when + "."
    if random.random() < URGENCY_RATE[priority]:
        level = priority
        if random.random() < WRONG_URGENCY_RATE:
            level = random.choice([p for p in URGENCY if p != priority])
        hint = random.choice(URGENCY[level])
        if hint:
            text += " " + hint
    text += fill(random.choice(SIGN_OFFS).replace("{name}", random.choice(NAMES)))
    if random.random() < 0.15:
        text = add_typo(text)
    if random.random() < 0.20:
        text = text.lower()
    return re.sub(r"\s+", " ", text).strip(), f"{subcategory}#{idx}"


def main():
    random.seed(SEED)
    df = pd.read_csv(IN_FILE)
    written = [write_ticket(s, p) for s, p in zip(df["subcategory"], df["priority"])]
    df["description"] = [w[0] for w in written]
    df["template_id"] = [w[1] for w in written]
    # Resolution notes for tickets that were resolved. A separate random generator is used so the
    # ticket descriptions above stay exactly the same as before (saved AI embeddings stay valid).
    note_rng = random.Random(SEED + 1000)
    df["resolution_note"] = [note_rng.choice(RESOLUTIONS[s]) if pd.notna(r) else ""
                             for s, r in zip(df["subcategory"], df["resolved_at"])]
    df["correct_group"] = df["category"].map(CORRECT_GROUP)
    df["misrouted"] = (df["assignment_group"] != df["correct_group"]).astype(int)

    cols = ["incident_id", "opened_at", "description", "priority", "category", "subcategory",
            "assignment_group", "correct_group", "misrouted", "template_id", "resolution_note"]
    df[cols].to_csv(OUT_FILE, index=False)

    print(f"Wrote {len(df)} tickets to {OUT_FILE}")
    print(f"Misrouted tickets (sent to the wrong team): {df['misrouted'].sum()} "
          f"({df['misrouted'].mean():.1%})")
    print("\nFive random examples:")
    for _, r in df.sample(5, random_state=1).iterrows():
        print(f"  [{r['priority']} | {r['category']} > {r['subcategory']}] {r['description']}")


if __name__ == "__main__":
    main()
