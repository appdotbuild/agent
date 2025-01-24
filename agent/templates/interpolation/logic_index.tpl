import { GenericHandler } from "../common/handler";
{% for handler in handlers %}
import {{ handler.name }} from "./{{ handler.name }}"

export const handlers: {[key: string]: GenericHandler<any[], any>} = {{% for handler in handlers %}
    '{{ handler.name }}': {{ handler.name }},{% endfor %}
};