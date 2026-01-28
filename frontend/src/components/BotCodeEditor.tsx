import CodeMirror from '@uiw/react-codemirror';
import { python } from '@codemirror/lang-python';
import { oneDark } from '@codemirror/theme-one-dark';

interface BotCodeEditorProps {
  value: string;
  onChange: (value: string) => void;
  id?: string;
}

export function BotCodeEditor({ value, onChange, id }: BotCodeEditorProps) {
  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      extensions={[python()]}
      theme={oneDark}
      height="256px"
      basicSetup={{
        lineNumbers: true,
        foldGutter: false,
        highlightActiveLine: true,
      }}
      className="rounded-md border border-input overflow-hidden text-sm"
      id={id}
    />
  );
}
