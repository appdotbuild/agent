import { GenericHandler } from "../common/handler";
{% for handler_name, handler in handlers.items() %}
import { {{ handler.name }} } from "../handlers/{{ handler.module }}";
{% endfor %}

export const handlers: {[key: string]: GenericHandler<any, any>} = {
    {% for handler_name, handler in handlers.items() %}
    '{{ handler_name }}': {{ handler.name }},
    {% endfor %}
};