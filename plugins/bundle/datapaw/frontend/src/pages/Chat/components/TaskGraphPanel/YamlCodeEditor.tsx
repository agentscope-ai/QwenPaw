import { useCallback, useMemo, useRef, type ChangeEvent } from 'react';
import styles from './YamlCodeEditor.module.less';

interface YamlCodeEditorProps {
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
}

function highlightYamlLine(line: string) {
  const listNodeMatch = line.match(/^(\s*- )(node_id)(:)( ?)(.+)$/);
  if (listNodeMatch) {
    return (
      <>
        <span className={styles.yamlPunctuation}>{listNodeMatch[1]}</span>
        <span className={styles.yamlKey}>
          {listNodeMatch[2]}
          {listNodeMatch[3]}
        </span>
        {listNodeMatch[4]}
        <span className={styles.yamlValue}>{listNodeMatch[5]}</span>
      </>
    );
  }

  const depListMatch = line.match(/^(\s+- )(.+)$/);
  if (depListMatch && !line.includes(':')) {
    return (
      <>
        <span className={styles.yamlPunctuation}>{depListMatch[1]}</span>
        <span className={styles.yamlValue}>{depListMatch[2]}</span>
      </>
    );
  }

  const kvMatch = line.match(/^(\s*)([A-Za-z_][\w]*)(:)( ?)(.*)$/);
  if (kvMatch) {
    return (
      <>
        {kvMatch[1]}
        <span className={styles.yamlKey}>
          {kvMatch[2]}
          {kvMatch[3]}
        </span>
        {kvMatch[4]}
        <span className={styles.yamlValue}>{kvMatch[5]}</span>
      </>
    );
  }

  return line || '\u00a0';
}

export default function YamlCodeEditor({ value, onChange, readOnly = false }: YamlCodeEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const highlightRef = useRef<HTMLPreElement>(null);
  const lineNumbersRef = useRef<HTMLDivElement>(null);

  const lines = useMemo(() => value.split('\n'), [value]);
  const lineCount = Math.max(lines.length, 16);

  const syncScroll = useCallback(() => {
    const textarea = textareaRef.current;
    const highlight = highlightRef.current;
    const lineNumbers = lineNumbersRef.current;
    if (!textarea) return;
    if (highlight) {
      highlight.scrollTop = textarea.scrollTop;
      highlight.scrollLeft = textarea.scrollLeft;
    }
    if (lineNumbers) lineNumbers.scrollTop = textarea.scrollTop;
  }, []);

  const handleChange = useCallback(
    (event: ChangeEvent<HTMLTextAreaElement>) => {
      onChange(event.target.value);
    },
    [onChange],
  );

  return (
    <div className={styles.editor}>
      <div ref={lineNumbersRef} className={styles.lineNumbers} aria-hidden>
        {Array.from({ length: lineCount }, (_, index) => (
          <div key={index + 1} className={styles.lineNumber}>
            {index + 1}
          </div>
        ))}
      </div>

      <div className={styles.codeArea}>
        <pre ref={highlightRef} className={styles.highlight} aria-hidden>
          {lines.map((line, index) => (
            <div key={index} className={styles.codeLine}>
              {highlightYamlLine(line)}
            </div>
          ))}
        </pre>
        <textarea
          ref={textareaRef}
          className={styles.textarea}
          value={value}
          onChange={handleChange}
          onScroll={syncScroll}
          spellCheck={false}
          readOnly={readOnly}
          aria-label="Plan YAML editor"
        />
      </div>
    </div>
  );
}
