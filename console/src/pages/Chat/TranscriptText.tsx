import { FileReferenceChip } from "./RichFileReferenceInput";
import { splitFileReferences } from "./fileReferenceFormatting";

/** The same compact references in live messages and replayed history. */
export function TranscriptText({ text }: { text: string }) {
  return <div style={{whiteSpace: "pre-wrap", overflowWrap: "anywhere"}}>
    {splitFileReferences(text).map((part, index) => part.reference
      ? <FileReferenceChip key={index} reference={part.reference} />
      : <span key={index}>{part.text}</span>)}
  </div>;
}
