import { useId } from "react";
import { Select as SelectPrimitive } from "radix-ui";
import { Check, ChevronDown, ChevronUp } from "lucide-react";

type OptionGroup = {
  label?: string;
  options: { value: string; label: string }[];
};

export default function EvaluationSelect({
  label,
  value,
  onValueChange,
  groups,
  className = "",
}: {
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  groups: OptionGroup[];
  className?: string;
}) {
  const id = useId();
  const selected = groups
    .flatMap((group) => group.options)
    .find((option) => option.value === value);

  return (
    <div className={`evaluation-select-field ${className}`}>
      <label htmlFor={id}>{label}</label>
      <SelectPrimitive.Root value={value} onValueChange={onValueChange}>
        <SelectPrimitive.Trigger
          id={id}
          className="evaluation-select"
          title={selected?.label}
        >
          <SelectPrimitive.Value className="evaluation-select-value" />
          <SelectPrimitive.Icon className="evaluation-select-icon">
            <ChevronDown size={14} strokeWidth={1.5} />
          </SelectPrimitive.Icon>
        </SelectPrimitive.Trigger>
        <SelectPrimitive.Portal>
          <SelectPrimitive.Content
            className="evaluation-select-content"
            position="popper"
            align="start"
            sideOffset={6}
            collisionPadding={12}
          >
            <SelectPrimitive.ScrollUpButton className="evaluation-select-scroll">
              <ChevronUp size={14} strokeWidth={1.5} />
            </SelectPrimitive.ScrollUpButton>
            <SelectPrimitive.Viewport className="evaluation-select-viewport">
              {groups.map((group, index) => (
                <SelectPrimitive.Group key={group.label ?? index}>
                  {group.label && (
                    <SelectPrimitive.Label className="evaluation-select-label">
                      {group.label}
                    </SelectPrimitive.Label>
                  )}
                  {group.options.map((option) => (
                    <SelectPrimitive.Item
                      key={option.value}
                      value={option.value}
                      className="evaluation-select-item"
                    >
                      <SelectPrimitive.ItemText>
                        {option.label}
                      </SelectPrimitive.ItemText>
                      <SelectPrimitive.ItemIndicator className="evaluation-select-indicator">
                        <Check size={16} strokeWidth={1.5} />
                      </SelectPrimitive.ItemIndicator>
                    </SelectPrimitive.Item>
                  ))}
                </SelectPrimitive.Group>
              ))}
            </SelectPrimitive.Viewport>
            <SelectPrimitive.ScrollDownButton className="evaluation-select-scroll">
              <ChevronDown size={14} strokeWidth={1.5} />
            </SelectPrimitive.ScrollDownButton>
          </SelectPrimitive.Content>
        </SelectPrimitive.Portal>
      </SelectPrimitive.Root>
    </div>
  );
}
