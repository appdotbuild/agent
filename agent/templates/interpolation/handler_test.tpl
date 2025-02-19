import { afterEach, beforeEach } from "bun:test";
import { resetDB, createDB } from "../../helpers";
{{handler_function_import}}
{{imports}}

describe("{{handler_name}}", () => {
    beforeEach(async () => {
        await createDB();
    });

    afterEach(async () => {
        await resetDB();
    });
    {% for test in tests %}
    {{test|indent(4)}}
    {% endfor %}
});