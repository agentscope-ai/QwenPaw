/**
 * Reranker validation-visibility helpers.
 *
 * The reranker detail fields stay mounted inside #reranker-details (hidden with
 * display:none when collapsed) so that full-form validation still catches
 * missing or invalid values. If an error lands on one of those fields while the
 * section is collapsed, `validateFields()` rejects the save but the user never
 * sees why, so the section has to be expanded instead.
 */

/** Path of the reranker switch, the only reranker field outside the details. */
export const RERANKER_ENABLED_PATH = [
  "reme_light_memory_config",
  "reranker_config",
  "enabled",
] as const;

/** Shape of an antd `FieldError` entry as handed to `onFieldsChange`. */
export interface RerankerFieldError {
  name: ReadonlyArray<string | number>;
  errors?: readonly string[];
}

/**
 * True when a reranker details field carries a validation error. `enabled` is
 * rendered outside #reranker-details, so an error there must never expand it.
 */
export function isRerankerDetailFieldError(field: RerankerFieldError): boolean {
  const [group, subgroup, leaf] = field.name;
  return (
    group === "reme_light_memory_config" &&
    subgroup === "reranker_config" &&
    leaf !== "enabled" &&
    (field.errors?.length ?? 0) > 0
  );
}

/**
 * True when reranking is enabled and any collapsed details field is invalid.
 */
export function rerankerDetailsHaveErrors(
  allFields: readonly RerankerFieldError[],
  rerankerEnabled: boolean,
): boolean {
  return rerankerEnabled && allFields.some(isRerankerDetailFieldError);
}

/**
 * Form `onFieldsChange` handler that expands the reranker details when a
 * validation error appears on one of their fields. Kept out of the page so the
 * field set can be unit-tested without rendering AgentConfigPage.
 */
export function handleRerankerFieldsChange(
  form: { getFieldValue: (name: readonly (string | number)[]) => unknown },
  setRerankerExpanded: (expanded: boolean) => void,
): (
  _changedFields: readonly RerankerFieldError[],
  allFields: readonly RerankerFieldError[],
) => void {
  return (_changedFields, allFields) => {
    const rerankerEnabled = !!form.getFieldValue(RERANKER_ENABLED_PATH);
    if (rerankerDetailsHaveErrors(allFields, rerankerEnabled)) {
      setRerankerExpanded(true);
    }
  };
}
