"""Colour themes shared by the change page and the session page: the ids, the localStorage key, the head script that applies the stored pick before first
paint, and the picker. The palettes live in assets/ui/page2.css (:root holds the shared tokens and the navy values, every other theme is a [data-theme] block)."""
import html
import json

def esc(s):
    return html.escape(str(s), quote=True)


THEMES = ('midnight', 'navy', 'ocean', 'plum', 'graphite', 'pearl')  # the first is the default
THEME_KEY = 'explain-change-theme'  # localStorage key of the reader's pick, the same on both pages


def head_script():
    """Runs in <head>, before the style and the body: applies the reader's stored pick (or the baked default) so the first paint is in the right theme."""
    return ("<script>(function(){var d=document.documentElement,a=%s,t=d.getAttribute('data-theme');try{var s=localStorage.getItem('%s');if(a.indexOf(s)>-1)t=s}catch(e){}"
            "d.setAttribute('data-theme',t);d.classList.add('js')})()</script>" % (json.dumps(list(THEMES)), THEME_KEY))


def picker(t, theme):
    """The labelled native select. `t`: the strings of the page language."""
    opts = ''.join('<option value="%s"%s>%s</option>' % (k, ' selected' if k == theme else '', esc(t['ses_theme_' + k])) for k in THEMES)
    return '<label class="picker"><span>%s</span><select id="skin" name="skin">%s</select></label>' % (esc(t['ses_theme_label']), opts)
