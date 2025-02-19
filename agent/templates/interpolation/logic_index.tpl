import { GenericHandler } from "../common/handler";

{% for handler_name, handler in handlers.items() %}
import { {{ handler_name }} } from "../handlers/{{ handler.module }}";
{% endfor %}

{% if use_perplexity %}
{% for handler_name in custom_handlers.keys() %}
import { {{ handler_name }} } from "../handlers/perplexity_handler";  // TODO: implement for custom handlers
{% endfor %}
{% endif %}

export const handlers: {[key: string]: GenericHandler<any, any>} = {
    {% for handler_name in handlers.keys() %}
    '{{ handler_name }}': {{ handler_name }},
    {% endfor %}
    {% if custom_handlers is not none %}
    {% for handler_name in custom_handlers.keys() %}
    '{{ custom_handlers[handler_name] }}': {{ handler_name }},
    {% endfor %}
    {% endif %}
};