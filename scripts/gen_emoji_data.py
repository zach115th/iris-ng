#!/usr/bin/env python3
"""Generate ui/public/assets/js/iris/emoji_data.js (the war-room Stream's emoji picker and :shortcode:
completion) from Unicode's emoji-test.txt.

    python scripts/gen_emoji_data.py <emoji-test.txt> [out.js] [--max-version 14.0]

emoji-test.txt: https://unicode.org/Public/emoji/latest/emoji-test.txt (Unicode terms of use apply:
https://www.unicode.org/terms_of_use.html). Kept: fully-qualified emoji of the nine picker groups up to
--max-version (newer ones show as empty boxes on many systems), without skin-tone variants. Each entry is
[emoji, name, shortcode]; the shortcode is the name in lower case with underscores. A few common aliases
(:+1:, :tada:, :white_check_mark:...) map onto entries of the list.
"""
import json
import re
import sys

GROUPS = (('Smileys & Emotion', 'smileys', 'Smileys & emotion'), ('People & Body', 'people', 'People & body'),
          ('Animals & Nature', 'animals', 'Animals & nature'), ('Food & Drink', 'food', 'Food & drink'),
          ('Travel & Places', 'travel', 'Travel & places'), ('Activities', 'activities', 'Activities'),
          ('Objects', 'objects', 'Objects'), ('Symbols', 'symbols', 'Symbols'), ('Flags', 'flags', 'Flags'))

ALIASES = {
    '+1': 'thumbs up', 'thumbsup': 'thumbs up', '-1': 'thumbs down', 'thumbsdown': 'thumbs down',
    'smile': 'grinning face with smiling eyes', 'smiley': 'grinning face with big eyes',
    'grin': 'beaming face with smiling eyes', 'laughing': 'grinning squinting face', 'joy': 'face with tears of joy',
    'wink': 'winking face', 'blush': 'smiling face with smiling eyes', 'heart_eyes': 'smiling face with heart-eyes',
    'thinking': 'thinking face', 'neutral_face': 'neutral face', 'confused': 'confused face', 'cry': 'crying face',
    'sob': 'loudly crying face', 'rage': 'enraged face', 'scream': 'face screaming in fear',
    'sweat_smile': 'grinning face with sweat', 'sunglasses': 'smiling face with sunglasses', 'heart': 'red heart',
    'broken_heart': 'broken heart', 'tada': 'party popper', 'rocket': 'rocket', 'fire': 'fire', 'eyes': 'eyes',
    '100': 'hundred points', 'ok_hand': 'OK hand', 'clap': 'clapping hands', 'pray': 'folded hands',
    'wave': 'waving hand', 'muscle': 'flexed biceps', 'raised_hands': 'raising hands',
    'white_check_mark': 'check mark button', 'heavy_check_mark': 'check mark', 'x': 'cross mark',
    'warning': 'warning', 'rotating_light': 'police car light', 'bug': 'bug', 'lock': 'locked',
    'unlock': 'unlocked', 'key': 'key', 'shield': 'shield', 'skull': 'skull', 'zap': 'high voltage',
    'boom': 'collision', 'bulb': 'light bulb', 'mag': 'magnifying glass tilted left', 'memo': 'memo',
    'pushpin': 'pushpin', 'hourglass': 'hourglass done', 'stopwatch': 'stopwatch', 'bell': 'bell',
    'question': 'red question mark', 'exclamation': 'red exclamation mark', 'no_entry': 'no entry',
    'construction': 'construction', 'computer': 'laptop', 'link': 'link', 'see_no_evil': 'see-no-evil monkey',
    'facepalm': 'person facepalming', 'shrug': 'person shrugging', 'coffee': 'hot beverage', 'sparkles': 'sparkles',
    'star': 'star', 'checkered_flag': 'chequered flag', 'triangular_flag_on_post': 'triangular flag',
    'handshake': 'handshake', 'robot': 'robot', 'ghost': 'ghost', 'chart_with_upwards_trend': 'chart increasing',
    'chart_with_downwards_trend': 'chart decreasing', 'email': 'e-mail', 'gear': 'gear', 'wrench': 'wrench',
    'hammer': 'hammer', 'package': 'package', 'satellite': 'satellite antenna', 'biohazard': 'biohazard',
    'radioactive': 'radioactive', 'stop_sign': 'stop sign', 'calendar': 'calendar', 'clipboard': 'clipboard',
}

LINE = re.compile(r'^([0-9A-F ]+?)\s*;\s*fully-qualified\s*#\s*(\S+)\s+E(\d+\.\d+)\s+(.+)$')
SKIN = {0x1F3FB, 0x1F3FC, 0x1F3FD, 0x1F3FE, 0x1F3FF}


def shortcode(name):
    s = re.sub(r'[^a-z0-9+\-]+', '_', name.lower().replace('’', '').replace("'", '')).strip('_')
    return re.sub(r'_+', '_', s)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    max_version = 14.0
    if '--max-version' in sys.argv:
        max_version = float(sys.argv[sys.argv.index('--max-version') + 1])
        args = [a for a in args if a != str(sys.argv[sys.argv.index('--max-version') + 1])]
    if not args:
        sys.exit(__doc__)
    src = args[0]
    out = args[1] if len(args) > 1 else 'ui/public/assets/js/iris/emoji_data.js'
    labels = {g: (k, lbl) for g, k, lbl in GROUPS}
    groups, by_name, used, version = {}, {}, set(), '?'
    current = None
    for raw in open(src, encoding='utf-8'):
        line = raw.rstrip('\n')
        if line.startswith('# Version:'):
            version = line.split(':', 1)[1].strip()
        if line.startswith('# group:'):
            current = line.split(':', 1)[1].strip()
            continue
        if current not in labels:
            continue
        m = LINE.match(line)
        if not m:
            continue
        cps = [int(x, 16) for x in m.group(1).split()]
        if SKIN & set(cps) or float(m.group(3)) > max_version:
            continue
        char = ''.join(chr(c) for c in cps)
        name = m.group(4).strip()
        code = shortcode(name)
        base, n = code, 2
        while code in used:
            code, n = '%s_%d' % (base, n), n + 1
        used.add(code)
        groups.setdefault(current, []).append([char, name, code])
        by_name[name.lower()] = char
    aliases = {}
    for alias, name in ALIASES.items():
        char = by_name.get(name.lower())
        if char is None:
            print('alias :%s: has no entry named %r - skipped' % (alias, name), file=sys.stderr)
            continue
        aliases[alias] = char
    data = {'version': version, 'max_version': max_version,
            'groups': [{'key': labels[g][0], 'label': labels[g][1], 'emoji': groups.get(g, [])}
                       for g, _, _ in GROUPS if groups.get(g)],
            'aliases': aliases}
    total = sum(len(g['emoji']) for g in data['groups'])
    body = json.dumps(data, ensure_ascii=True, separators=(',', ':'))
    with open(out, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('/* Emoji for the war-room Stream (picker, :shortcode: completion). Generated by\n'
                 ' * scripts/gen_emoji_data.py from Unicode emoji-test.txt (Emoji %s, entries up to %s, no skin-tone\n'
                 ' * variants) - (c) Unicode, Inc., https://www.unicode.org/terms_of_use.html . Do not edit by hand. */\n'
                 'window.IrisEmojiData = %s;\n' % (version, max_version, body))
    print('%d emoji in %d groups, %d aliases -> %s' % (total, len(data['groups']), len(aliases), out))


if __name__ == '__main__':
    main()
