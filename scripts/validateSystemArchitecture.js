const fs = require('fs');
const path = require('path');

const repoRoot = path.resolve(__dirname, '..');
const graphRelativePath = path.join('design', 'KG', 'SystemArchitecture.json');
const graphPath = path.join(repoRoot, graphRelativePath);
const schemaPathCandidates = [
    path.join(repoRoot, 'schema', 'SystemArchitecture.schema.json'),
];

const {
    elementTypeMetadata,
    relationshipCategoryByType,
    validateRelationshipEndpointTypes,
} = require('./archimate32-rules');

function main() {
    const schemaPath = schemaPathCandidates.find(candidate => fs.existsSync(candidate));
    if (!schemaPath) {
        fail(`Schema file is missing. Checked: ${schemaPathCandidates.map(candidate => path.relative(repoRoot, candidate)).join(', ')}`);
    }

    if (!fs.existsSync(graphPath)) {
        fail('System architecture file is missing at design/KG/SystemArchitecture.json');
    }

    const schema = parseJson(schemaPath, path.relative(repoRoot, schemaPath));
    const document = parseJson(graphPath, 'design/KG/SystemArchitecture.json');
    const errors = [];

    validateAgainstSchema(document, schema, '#', errors, schema);
    validateGraphSemantics(document, errors);

    if (errors.length > 0) {
        console.error('SystemArchitecture validation failed:');
        for (const error of errors) {
            console.error(`- ${error}`);
        }
        process.exit(1);
    }

    console.log('SystemArchitecture validation passed for: design/KG/SystemArchitecture.json');
}

function parseJson(filePath, label) {
    try {
        return JSON.parse(fs.readFileSync(filePath, 'utf8'));
    } catch (error) {
        fail(`Failed to parse ${label}: ${String(error)}`);
    }
}

function validateAgainstSchema(value, schemaNode, pointer, errors, rootSchema) {
    if (!schemaNode || typeof schemaNode !== 'object') {
        return;
    }

    const resolvedSchema = schemaNode.$ref ? resolveRef(schemaNode.$ref, rootSchema, errors, pointer) : schemaNode;
    if (!resolvedSchema) {
        return;
    }

    if (resolvedSchema.const !== undefined && !isDeepStrictEqual(value, resolvedSchema.const)) {
        errors.push(`${pointer} must equal ${JSON.stringify(resolvedSchema.const)}`);
        return;
    }

    if (resolvedSchema.enum && !resolvedSchema.enum.some(option => isDeepStrictEqual(option, value))) {
        errors.push(`${pointer} must be one of: ${resolvedSchema.enum.map(option => JSON.stringify(option)).join(', ')}`);
        return;
    }

    if (resolvedSchema.type !== undefined) {
        validateType(value, resolvedSchema.type, pointer, errors);
        if (!typeMatches(value, resolvedSchema.type)) {
            return;
        }
    }

    if (typeof resolvedSchema.minLength === 'number') {
        if (typeof value !== 'string' || value.length < resolvedSchema.minLength) {
            errors.push(`${pointer} must be at least ${resolvedSchema.minLength} character(s) long`);
        }
    }

    if (typeof resolvedSchema.maxLength === 'number') {
        if (typeof value !== 'string' || value.length > resolvedSchema.maxLength) {
            errors.push(`${pointer} must be at most ${resolvedSchema.maxLength} character(s) long`);
        }
    }

    if (resolvedSchema.pattern) {
        const matcher = new RegExp(resolvedSchema.pattern);
        if (typeof value !== 'string' || !matcher.test(value)) {
            errors.push(`${pointer} must match pattern ${JSON.stringify(resolvedSchema.pattern)}`);
        }
    }

    if (typeof resolvedSchema.minimum === 'number') {
        if (typeof value !== 'number' || value < resolvedSchema.minimum) {
            errors.push(`${pointer} must be >= ${resolvedSchema.minimum}`);
        }
    }

    if (typeof resolvedSchema.maximum === 'number') {
        if (typeof value !== 'number' || value > resolvedSchema.maximum) {
            errors.push(`${pointer} must be <= ${resolvedSchema.maximum}`);
        }
    }

    if (typeof resolvedSchema.minItems === 'number') {
        if (!Array.isArray(value) || value.length < resolvedSchema.minItems) {
            errors.push(`${pointer} must contain at least ${resolvedSchema.minItems} item(s)`);
        }
    }

    if (typeof resolvedSchema.maxItems === 'number') {
        if (!Array.isArray(value) || value.length > resolvedSchema.maxItems) {
            errors.push(`${pointer} must contain at most ${resolvedSchema.maxItems} item(s)`);
        }
    }

    if (resolvedSchema.uniqueItems === true && Array.isArray(value)) {
        const seen = new Set();
        value.forEach((entry, index) => {
            const serialized = JSON.stringify(entry);
            if (seen.has(serialized)) {
                errors.push(`${pointer}[${index}] must be unique within ${pointer}`);
            } else {
                seen.add(serialized);
            }
        });
    }

    if (resolvedSchema.type === 'object') {
        validateObject(value, resolvedSchema, pointer, errors, rootSchema);
        return;
    }

    if (resolvedSchema.type === 'array') {
        validateArray(value, resolvedSchema, pointer, errors, rootSchema);
    }
}

function validateObject(value, schemaNode, pointer, errors, rootSchema) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return;
    }

    const properties = schemaNode.properties || {};
    const required = Array.isArray(schemaNode.required) ? schemaNode.required : [];

    for (const key of required) {
        if (!(key in value)) {
            errors.push(`${pointer} is missing required property '${key}'`);
        }
    }

    if (schemaNode.additionalProperties === false) {
        for (const key of Object.keys(value)) {
            if (!(key in properties)) {
                errors.push(`${pointer} contains unsupported property '${key}'`);
            }
        }
    }

    for (const [key, propertySchema] of Object.entries(properties)) {
        if (key in value) {
            validateAgainstSchema(value[key], propertySchema, `${pointer}.${key}`, errors, rootSchema);
        }
    }
}

function validateArray(value, schemaNode, pointer, errors, rootSchema) {
    if (!Array.isArray(value)) {
        return;
    }

    if (schemaNode.items) {
        value.forEach((entry, index) => {
            validateAgainstSchema(entry, schemaNode.items, `${pointer}[${index}]`, errors, rootSchema);
        });
    }
}

function validateType(value, expectedType, pointer, errors) {
    if (!typeMatches(value, expectedType)) {
        const printableType = Array.isArray(expectedType) ? expectedType.join(' or ') : expectedType;
        errors.push(`${pointer} must be of type ${printableType}`);
    }
}

function typeMatches(value, expectedType) {
    if (Array.isArray(expectedType)) {
        return expectedType.some(candidate => typeMatches(value, candidate));
    }

    switch (expectedType) {
        case 'object':
            return value !== null && typeof value === 'object' && !Array.isArray(value);
        case 'array':
            return Array.isArray(value);
        case 'string':
            return typeof value === 'string';
        case 'number':
            return typeof value === 'number' && Number.isFinite(value);
        case 'integer':
            return typeof value === 'number' && Number.isInteger(value);
        case 'boolean':
            return typeof value === 'boolean';
        case 'null':
            return value === null;
        default:
            return true;
    }
}

function resolveRef(ref, rootSchema, errors, pointer) {
    if (!ref.startsWith('#/')) {
        errors.push(`${pointer} uses unsupported $ref '${ref}'`);
        return undefined;
    }

    const segments = ref.slice(2).split('/');
    let current = rootSchema;
    for (const segment of segments) {
        if (!current || typeof current !== 'object' || !(segment in current)) {
            errors.push(`${pointer} references missing schema path '${ref}'`);
            return undefined;
        }
        current = current[segment];
    }

    return current;
}

function validateGraphSemantics(document, errors) {
    if (!document || typeof document !== 'object') {
        return;
    }

    const elements = Array.isArray(document.elements) ? document.elements : [];
    const relationships = Array.isArray(document.relationships) ? document.relationships : [];
    const views = Array.isArray(document.views) ? document.views : [];

    const elementById = new Map();
    const relationshipById = new Map();

    for (const element of elements) {
        if (!element || typeof element !== 'object') {
            continue;
        }

        if (elementById.has(element.id)) {
            errors.push(`elements contains duplicate id '${element.id}'`);
            continue;
        }

        elementById.set(element.id, element);

        const expectedMetadata = elementTypeMetadata.get(element.type);
        if (!expectedMetadata) {
            errors.push(`elements '${element.id}' uses unsupported ArchiMate element type '${element.type}'`);
            continue;
        }
    }

    for (const element of elements) {
        if (!element || typeof element !== 'object' || !element.parent) {
            continue;
        }

        if (!elementById.has(element.parent)) {
            errors.push(`elements '${element.id}' references missing parent '${element.parent}'`);
        }
    }

    for (const relationship of relationships) {
        if (!relationship || typeof relationship !== 'object') {
            continue;
        }

        if (relationshipById.has(relationship.id)) {
            errors.push(`relationships contains duplicate id '${relationship.id}'`);
            continue;
        }

        relationshipById.set(relationship.id, relationship);

        const expectedCategory = relationshipCategoryByType.get(relationship.type);
        if (!expectedCategory) {
            errors.push(`relationships '${relationship.id}' uses unsupported ArchiMate relationship type '${relationship.type}'`);
        }

        const source = elementById.get(relationship.source_id);
        if (!source) {
            errors.push(`relationships '${relationship.id}' references missing source_id '${relationship.source_id}'`);
        } else if (relationship.source_name !== source.name) {
            errors.push(`relationships '${relationship.id}' source_name '${relationship.source_name}' does not match element '${relationship.source_id}' name '${source.name}'`);
        }

        const target = elementById.get(relationship.target_id);
        if (!target) {
            errors.push(`relationships '${relationship.id}' references missing target_id '${relationship.target_id}'`);
        } else if (relationship.target_name !== target.name) {
            errors.push(`relationships '${relationship.id}' target_name '${relationship.target_name}' does not match element '${relationship.target_id}' name '${target.name}'`);
        }

        if (source && target) {
            errors.push(...validateRelationshipEndpointTypes(relationship, source, target));
        }
    }

    const topLevelViews = views.filter(view => view && typeof view === 'object' && !view.parent_element_id);
    if (topLevelViews.length !== 1) {
        errors.push(`views must contain exactly one top-level view named 'SystemArchitecture'; found ${topLevelViews.length}`);
    } else if (topLevelViews[0].view_name !== 'SystemArchitecture') {
        errors.push(`top-level view '${topLevelViews[0].view_id}' view_name must be 'SystemArchitecture'`);
    }

    const elementIdsIncludedInViews = new Set();
    const relationshipIdsIncludedInViews = new Set();
    for (const view of views) {
        if (!view || typeof view !== 'object') {
            continue;
        }

        if (!view.parent_element_id && view.view_name !== 'SystemArchitecture') {
            errors.push(`views '${view.view_id}' must declare parent_element_id unless it is the top-level SystemArchitecture view`);
        }

        if (view.parent_element_id) {
            const parent = elementById.get(view.parent_element_id);
            if (!parent) {
                errors.push(`views '${view.view_id}' references missing parent_element_id '${view.parent_element_id}'`);
            } else if (view.parent_element_name && view.parent_element_name !== parent.name) {
                errors.push(`views '${view.view_id}' parent_element_name '${view.parent_element_name}' does not match element '${view.parent_element_id}' name '${parent.name}'`);
            }
        }

        const includedElements = Array.isArray(view.included_elements) ? view.included_elements : [];
        if (includedElements.length > 7) {
            errors.push(`views '${view.view_id}' must contain at most 7 elements; found ${includedElements.length}. Split the content into layered sub-views before adding more elements.`);
        }
        includedElements.forEach(elementId => {
            elementIdsIncludedInViews.add(elementId);
            if (!elementById.has(elementId)) {
                errors.push(`views '${view.view_id}' references missing included element '${elementId}'`);
            }
        });

        const includedRelationships = Array.isArray(view.included_relationships) ? view.included_relationships : [];
        includedRelationships.forEach(relationshipId => {
            relationshipIdsIncludedInViews.add(relationshipId);
            if (!relationshipById.has(relationshipId)) {
                errors.push(`views '${view.view_id}' references missing included relationship '${relationshipId}'`);
            }
        });
    }

    for (const element of elements) {
        if (element && typeof element === 'object' && !elementIdsIncludedInViews.has(element.id)) {
            errors.push(`elements '${element.id}' must be included in at least one view`);
        }
    }

    for (const relationship of relationships) {
        if (relationship && typeof relationship === 'object' && !relationshipIdsIncludedInViews.has(relationship.id)) {
            errors.push(`relationships '${relationship.id}' must be included in at least one view`);
        }
    }
}

function isDeepStrictEqual(left, right) {
    return JSON.stringify(left) === JSON.stringify(right);
}

function fail(message) {
    console.error(`SystemArchitecture validation failed: ${message}`);
    process.exit(1);
}

main();