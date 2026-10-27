"""Preserve four literal LaTeX delimiter escapes in otherwise valid JSON.

Call only after strict decoding failed on an unescaped delimiter. This is a
single lexical pass, not JSON completion, schema repair or formula correction.
"""


def escape_delimiters(text: str) -> str:
    parts=[];inside=False;index=0
    while index<len(text):
        char=text[index]
        if inside and char=='\\' and index+1<len(text):
            following=text[index+1]
            if following in '()[]':parts.append('\\')
            # Consume pairs so escaped quotes and even backslash runs retain
            # their original JSON meaning; do not scan them as new escapes.
            parts.append(text[index:index+2]);index+=2
            continue
        if char=='"':inside=not inside
        parts.append(char);index+=1
    return ''.join(parts)
