import autonetkit.log as log
import time
import textfsm
import pika
import json
import pprint
import autonetkit.plugins.process_data as process_data

def send(nidb, server, command, hosts, threads = 5):
# netaddr IP addresses not JSON serializable
    hosts = [str(h) for h in hosts]


    www_connection = pika.BlockingConnection(pika.ConnectionParameters(
            host='115.146.94.68'))
    www_channel = www_connection.channel()

    www_channel.exchange_declare(exchange='www',
            type='direct')

    connection = pika.BlockingConnection(pika.ConnectionParameters(
        host='115.146.94.68'))
    channel = connection.channel()

    channel.exchange_declare(exchange='measure',
            type='direct')

    data = {
            'command': command,
            "hosts": hosts,
            "threads": threads,
            }

    body = json.dumps(data)
    channel.basic_publish(exchange='measure',
            routing_key = server,
            body= body)
    #connection.close()

    hosts_received = set(hosts)

    # parsing function mappings
    parsing = {
            'vtysh -c "show ip route"': process_data.sh_ip_route,
            "traceroute": process_data.traceroute,
            }
    
    def callback(ch, method, properties, body):
        #TODO: send update to tornado web queue...
        data = json.loads(body)
        for host, host_data in data.items():
            for command, command_result in host_data.items():
                command_result = command_result.replace("\\r\\n", "\n")
                if command in parsing:
                    log.info( "%s %s" % (host, command))
                    parse_command = parsing[command]
                    parse_command(nidb, command_result)
                elif "traceroute" in command:
                    dst = command.split()[-1]   # last argument is the dst ip
                    src_host = process_data.reverse_tap_lookup(nidb, host)
                    dst_host = process_data.reverse_lookup(nidb, dst)
                    log.debug("Trace from %s to %s" % (src_host, dst_host))
                    parse_command = parsing["traceroute"]
                    log.info(command_result)
                    trace_result = parse_command(nidb, command_result)
                    trace_result.insert(0, src_host) 
                    log.debug(trace_result)
                    print "trace result", trace_result
                    trace_result = [str(t.id) for t in trace_result if t] # make serializable
                    body = json.dumps(trace_result)
                    www_channel.basic_publish(exchange='www',
                            routing_key = "client",
                            body= body)
                else:
                    print "No parser defined for command %s" % command
                    print "Raw output:"
                    print command_result

            if host in hosts_received:
                hosts_received.remove(host) # remove from list of waiting hosts

            if not len(hosts_received):
                channel.stop_consuming()

            print

    # wait for responses
    result = channel.queue_declare(exclusive=True)
    queue_name = result.method.queue
    channel.queue_bind(exchange='measure',
                       queue=queue_name,
                       routing_key="result")

    channel.basic_consume(callback,
                      queue=queue_name,
                      no_ack=True)

    channel.start_consuming()

